#!/usr/bin/env python3

import hashlib
import json
from functools import cached_property
from pathlib import Path

import classyclick
import click
import psycopg2
import requests
from tqdm import tqdm


@classyclick.command(context_settings={'show_default': True})
class Push:
    input: Path = classyclick.argument()
    table: str = classyclick.option(default='pocketmoney-transactions')
    pg_host: str = classyclick.option(default='localhost')
    pg_port: int = classyclick.option(default=5432)
    pg_user: str = classyclick.option(default='postgres')
    pg_password: str = classyclick.option(default='changeme')
    pg_database: str = classyclick.option(default='dev')
    grafana_host: str = classyclick.option(default='localhost')
    grafana_port: int = classyclick.option(default=3000)
    grafana_user: str = classyclick.option(default='admin')
    grafana_password: str = classyclick.option(default='admin')
    dashboard: Path = classyclick.option(
        default=Path(__file__).parent / 'dashboard.sample.json', help='Path to the dashboard export'
    )
    reset: bool = classyclick.option(help='Reset the table and re-import the dashboard, even if they already exist')

    @cached_property
    def table_hash(self):
        return hashlib.sha256(self.table.encode()).hexdigest()

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
        return psycopg2.connect(
            host=self.pg_host,
            port=self.pg_port,
            database=self.pg_database,
            user=self.pg_user,
            password=self.pg_password,
        )

    @cached_property
    def grafana_client(self):
        client = GrafanaClient(self.grafana_host, self.grafana_port)
        client.auth = (self.grafana_user, self.grafana_password)
        return client

    def generate_documents(self):
        for trans in self.data['ICTransactionSplit']['data']:
            # Create a document ID from the transaction's primary key

            trans['amount'] = float(trans['amount'])
            trans['transaction'] = self.transactions[trans['transaction']]
            if trans['category']:
                trans['category'] = self.categories[trans['category']]

            yield trans

    def push(self):
        cursor = self.client.cursor()
        batch = []
        for trans in tqdm(self.generate_documents(), desc='Pushing transactions'):
            batch.append((trans['ID'], json.dumps(trans)))
            if len(batch) >= 100:
                cursor.executemany(
                    f'''INSERT INTO "{self.table}" (id, data) VALUES (%s, %s) ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data''',
                    batch,
                )
                batch = []
        if batch:
            cursor.executemany(
                f'''INSERT INTO "{self.table}" (id, data) VALUES (%s, %s) ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data''',
                batch,
            )
        self.client.commit()

    def setup(self):
        try:
            self.client.cursor().execute(f"""select id from "{self.table}" limit 1""")
            # table exists, assume initial setup is not required unless --reset is used
            if not self.reset:
                return
        except psycopg2.errors.UndefinedTable:
            """no table exists, assume initial setup is required, go ahead and setup everything"""
            self.client.rollback()

        click.echo('Setting up the table and dashboard...')
        self.client.cursor().execute(
            f'''
            DROP TABLE IF EXISTS "{self.table}";
            CREATE TABLE "{self.table}" (
                id TEXT PRIMARY KEY,
                data JSONB
            );

            CREATE INDEX idx_data_gin_{self.table_hash} ON "{self.table}" USING GIN (data);
            '''
        )
        self.client.commit()
        self.setup_grafana_datasource()
        self.setup_grafana_dashboard()

    def setup_grafana_datasource(self):
        """Create or update Grafana PostgreSQL datasource via API"""
        click.echo('Setting up Grafana datasource...')
        ds_name = 'grafana-postgresql-datasource'

        try:
            patch_uid = self.grafana_client.get_datasource_by_name(ds_name)['uid']
        except Exception:
            patch_uid = None

        datasource = {
            'name': ds_name,
            'type': 'grafana-postgresql-datasource',
            'typeName': 'PostgreSQL',
            'access': 'proxy',
            'url': 'postgres:5432',
            'user': self.pg_user,
            'database': '',
            'basicAuth': False,
            'isDefault': True,
            'jsonData': {
                'connMaxLifetime': 14400,
                'database': self.pg_database,
                'maxIdleConns': 100,
                'maxIdleConnsAuto': True,
                'maxOpenConns': 100,
                'postgresVersion': 1400,
                'sslmode': 'disable',
            },
            'secureJsonData': {'password': self.pg_password},
            'readOnly': False,
        }

        if patch_uid is None:
            self.grafana_client.create_datasource(datasource)
        else:
            self.grafana_client.update_datasource(patch_uid, datasource)

    def setup_grafana_dashboard(self):
        """Create or update Grafana PostgreSQL datasource via API"""
        click.echo('Setting up Grafana dashboard...')
        data = json.loads(self.dashboard.read_text())
        try:
            r = self.grafana_client.get_dashboard(data['uid'])
            data['id'] = r['dashboard']['id']
            data['version'] = r['dashboard']['version']
        except requests.exceptions.HTTPError:
            """dashboard does not exist, create new"""
            data['version'] = 1
        self.grafana_client.create_update_dashboard(data)

    def __call__(self):
        self.setup()
        self.push()


class GrafanaClient(requests.Session):
    def __init__(self, host, port, auth=None):
        super().__init__()
        self.base_url = f'http://{host}:{port}'
        self.auth = auth

    def request(self, method, url, **kwargs):
        return super().request(method, f'{self.base_url}/{url}', **kwargs)

    def get_datasource_by_name(self, name):
        response = self.get(f'api/datasources/name/{name}')
        response.raise_for_status()
        return response.json()

    def create_datasource(self, data):
        response = self.post('api/datasources', json=data)
        response.raise_for_status()
        return response.json()

    def update_datasource(self, uid, data):
        response = self.put(f'api/datasources/uid/{uid}', json=data)
        response.raise_for_status()
        return response.json()

    def create_update_dashboard(self, data):
        response = self.post('api/dashboards/db', json={'dashboard': data})
        response.raise_for_status()
        return response.json()

    def get_dashboard(self, uid):
        response = self.get(f'api/dashboards/uid/{uid}')
        response.raise_for_status()
        return response.json()


if __name__ == '__main__':
    Push()
