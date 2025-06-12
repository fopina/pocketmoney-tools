#!/usr/bin/env python3

import json
import tempfile
from functools import cached_property
from pathlib import Path

import classyclick
import click
import requests
from opensearchpy import NotFoundError, OpenSearch
from opensearchpy.helpers import streaming_bulk
from tqdm import tqdm


@classyclick.command()
class Push:
    input: Path = classyclick.Argument()
    index: str = classyclick.Option(default='pocketmoney-transactions')
    os_host: str = classyclick.Option(default='localhost')
    os_port: int = classyclick.Option(default=9200)
    osd_host: str = classyclick.Option(default='localhost')
    osd_port: int = classyclick.Option(default=5601)
    dashboard: Path = classyclick.Option(default='dashboard.ndjson', help='Path to the dashboard export')
    reset: bool = classyclick.Option(help='Reset the index and re-import the dashboard, even if they already exist')

    @cached_property
    def data(self):
        return json.loads(self.input.read_text())

    @cached_property
    def accounts(self):
        objs = {}
        for obj in self.data['ICAccount']['data']:
            if obj['ID'] in objs:
                raise ValueError(f'Account {obj["ID"]} already exists')
            objs[obj['ID']] = obj
        return objs

    @cached_property
    def categories(self):
        objs = {}
        for obj in self.data['ICCategory']['data']:
            if obj['ID'] in objs:
                raise ValueError(f'Category {obj["ID"]} already exists')
            objs[obj['ID']] = obj
        return objs

    @cached_property
    def transactions(self):
        objs = {}
        for obj in self.data['ICTransaction']['data']:
            if obj['ID'] in objs:
                raise ValueError(f'Transaction {obj["ID"]} already exists')
            obj['account'] = self.accounts[obj['account']]
            objs[obj['ID']] = obj
        return objs

    @cached_property
    def client(self):
        return OpenSearch(
            hosts=[{'host': self.os_host, 'port': self.os_port}],
            http_compress=True,
            use_ssl=False,
            verify_certs=False,
            ssl_show_warn=False,
        )

    @cached_property
    def osd_client(self):
        return OSDClient(self.osd_host, self.osd_port)

    def generate_documents(self):
        for trans in self.data['ICTransactionSplit']['data']:
            # Create a document ID from the transaction's primary key
            doc_id = trans['ID']
            del trans['ID']

            trans['amount'] = float(trans['amount'])
            trans['transaction'] = self.transactions[trans['transaction']]
            if trans['category']:
                trans['category'] = self.categories[trans['category']]

            # Prepare the document
            doc = {'_index': self.index, '_id': doc_id, '_source': trans}

            yield doc

    def push_to_os(self):
        items = streaming_bulk(
            self.client,
            self.generate_documents(),
            index=self.index,
            raise_on_error=False,
        )

        for success, failed in tqdm(
            items, total=len(self.data['ICTransactionSplit']['data']), desc='Pushing to OpenSearch'
        ):
            if not success:
                print('Errors:', json.dumps(failed, indent=2))

    def setup(self):
        try:
            self.client.indices.get(index=self.index)
            # index exists, assume initial setup is not required unless --reset is used
            if self.reset:
                self.client.indices.delete(index=self.index)
            else:
                return
        except NotFoundError:
            """no index exists, assume initial setup is required, go ahead and setup everything"""
        click.echo('Setting up the index, index pattern and dashboard...')
        r = self.osd_client.delete_index_pattern(self.index)
        if r.status_code != 404:
            r.raise_for_status()
        r = self.osd_client.create_index_pattern(self.index, 'transaction.date')
        r.raise_for_status()
        objs = [json.loads(line) for line in self.dashboard.read_text().splitlines()]
        for obj in objs:
            if obj.get('type') == 'visualization':
                for reference in obj.get('references', []):
                    if reference.get('type') == 'index-pattern':
                        reference['id'] = self.index

        with tempfile.NamedTemporaryFile(suffix='.ndjson') as f:
            temp = Path(f.name)
            temp.write_text('\n'.join(json.dumps(obj) for obj in objs))
            r = self.osd_client.import_object(temp, overwrite=True)
            r.raise_for_status()

    def __call__(self):
        self.setup()
        self.push_to_os()


class OSDClient(requests.Session):
    def __init__(self, host, port):
        super().__init__()
        self.base_url = f'http://{host}:{port}'
        self.headers['osd-xsrf'] = 'true'

    def request(self, method, url, **kwargs):
        return super().request(method, f'{self.base_url}/{url}', **kwargs)

    def create_index_pattern(self, name, time_field):
        return self.request(
            'POST',
            f'api/saved_objects/index-pattern/{name}',
            json={'attributes': {'title': name, 'timeFieldName': time_field}},
            headers={'osd-xsrf': 'true'},
        )

    def delete_index_pattern(self, name):
        return self.delete(
            f'api/saved_objects/index-pattern/{name}',
        )

    def export_dashboard(self, name):
        return self.post(
            'api/saved_objects/_export',
            json={'objects': [{'id': name, 'type': 'dashboard'}], 'includeReferencesDeep': True},
        )

    def import_object(self, file: Path, create_new_copies=False, overwrite=False):
        with file.open('r') as f:
            return self.post(
                'api/saved_objects/_import',
                params={'createNewCopies': create_new_copies, 'overwrite': overwrite},
                files={'file': f},
            )


if __name__ == '__main__':
    Push.click()
