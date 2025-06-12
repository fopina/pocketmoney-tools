#!/usr/bin/env python3

import csv
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import cached_property
from pathlib import Path

import classyclick
import click


@classyclick.command(context_settings={'show_default': True})
class Push:
    input: Path = classyclick.Argument()
    pocketmoney: Path = classyclick.Option(default='pocketmoney_db_dump.json', help='Path to the converted JSON file')
    account: str = classyclick.Option(help='PocketMoney account name. If not specified, it will in all accounts')
    date_format: str = classyclick.Option('-f', default='%Y-%m-%d', help='Date format in CSV')
    date_column: int = classyclick.Option('-d', default=0, help='0-index of the date column')
    description_column: int = classyclick.Option('-c', default=1, help='0-index of the description column')
    amount_column: int = classyclick.Option('-a', default=2, help='0-index of the amount column')

    @cached_property
    def data(self):
        return json.loads(self.pocketmoney.read_text())

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
    def input_data(self):
        transactions = []
        with self.input.open('r') as f:
            reader = csv.reader(f)
            next(reader)  # Skip the header row
            for row in reader:
                transactions.append(
                    Transaction(
                        datetime.strptime(row[self.date_column].split(' ')[0], self.date_format).date(),
                        row[self.description_column],
                        float(row[self.amount_column]),
                    )
                )
        return transactions

    def generate_documents(self):
        for trans in self.data['ICTransactionSplit']['data']:
            # Create a document ID from the transaction's primary key

            trans['amount'] = float(trans['amount'])
            trans['transaction'] = self.transactions[trans['transaction']]
            if self.account and trans['transaction'].get('account', {}).get('name', '').lower() != self.account.lower():
                continue
            if trans['category']:
                trans['category'] = self.categories[trans['category']]

            yield PocketTransaction(
                datetime.strptime(trans['transaction']['date'], '%Y-%m-%d').date(),
                f'{trans["transaction"]["name"]} / {(trans["category"] or {}).get("name", "")}',
                trans['amount'],
            )

    def __call__(self):
        pocket_transactions: list[Transaction] = list(self.generate_documents())
        csv_transactions: list[Transaction] = self.input_data
        # make sure both are sorted in descendent order to optimize search
        pocket_transactions.sort(reverse=True)
        csv_transactions.sort(reverse=True)

        matched = 0

        for ct in csv_transactions:
            for pt in pocket_transactions:
                if pt.matched:
                    continue
                if abs(ct.date - pt.date) > timedelta(days=5):
                    # don't match with more than 5 days apart
                    continue
                if ct.amount == pt.amount:
                    ct.matched = pt
                    pt.matched = ct
                    matched += 1
                    break

        all_transactions = csv_transactions.copy()
        # do not print out pocket transactions older than oldest csv transaction, as CSV is likely a partial export from bank
        last_date = csv_transactions[-1].date - timedelta(days=5)
        for pt in pocket_transactions:
            if pt.date < last_date:
                break
            if not pt.matched:
                all_transactions.append(pt)
        all_transactions.sort(reverse=True)

        for t in all_transactions:
            if t.matched:
                click.echo(t)
            else:
                click.secho(t, fg='red')

        click.secho(f'Stats: {matched} matched, {len(csv_transactions) - matched} not found', fg='yellow')


@dataclass
class Transaction:
    date: datetime.date
    description: str
    amount: float
    matched: 'Transaction' = field(compare=False, default=None)

    def __lt__(self, other):
        if not isinstance(other, Transaction):
            return NotImplemented
        return (self.date, self.description, self.amount) < (other.date, other.description, other.amount)

    def __eq__(self, other):
        if not isinstance(other, Transaction):
            return NotImplemented
        return (self.date, self.description, self.amount) == (other.date, other.description, other.amount)

    def __str__(self):
        return f'({self.__class__.__name__}) {self.date} {self.description} {self.amount}'


@dataclass
class PocketTransaction(Transaction):
    """just for tagging"""


if __name__ == '__main__':
    Push.click()
