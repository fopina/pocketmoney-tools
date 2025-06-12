#!/usr/bin/env python3

import json
import sqlite3
from pathlib import Path

import classyclick


@classyclick.command()
class DBLoader:
    """
    Convert any SQLite database to a JSON file.
    """

    TABLES_TO_DUMP = {
        # the transactions we want
        'ICTransaction',
        # extra details for each transaction (such as category link)
        'ICTransactionSplit',
        # account details
        'ICAccount',
        # category details
        'ICCategory',
    }

    db_path: Path = classyclick.Argument()
    output: Path = classyclick.Option(default='pocketmoney_db_dump.json', help='Path to save the converted JSON file')
    full: bool = classyclick.Option(help='Dump all tables, not just the pre-defined ones')

    def __call__(self):
        # Load the database
        db_data = self.load_pocketmoney_db()

        if db_data:
            # Print summary of tables and their row counts
            print('\nDatabase Summary:')
            print('-----------------')
            for table_name, table_info in db_data.items():
                print(f'\nTable: {table_name}')
                print(f'Number of rows: {len(table_info["data"])}')
                print('Columns:', ', '.join(col['name'] for col in table_info['schema']))

            with self.output.open('w') as f:
                json.dump(db_data, f, indent=2)
            print(f'\nFull database dump saved to {self.output}')

    def load_pocketmoney_db(self):
        """
        Load any SQLite database and return its contents as a dictionary.

        Args:
            db_path (str): Path to the SQLite database file

        Returns:
            dict: Dictionary containing the database contents
        """
        try:
            # Connect to the SQLite database
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row  # This enables column access by name

            # Get all tables in the database
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = cursor.fetchall()

            # Create a dictionary to store all data
            db_data = {}

            # For each table, get its schema and data
            for table in tables:
                table_name = table[0]
                if not self.full and table_name not in self.TABLES_TO_DUMP:
                    continue

                # Get table schema
                cursor.execute(f'PRAGMA table_info({table_name});')
                columns = cursor.fetchall()

                # Get table data
                cursor.execute(f'SELECT * FROM {table_name};')
                rows = cursor.fetchall()

                # Convert rows to list of dictionaries
                table_data = []
                for row in rows:
                    row_dict = dict(row)
                    # Convert any binary data to hex string for JSON serialization
                    for key, value in row_dict.items():
                        if isinstance(value, bytes):
                            row_dict[key] = value.hex()
                    table_data.append(row_dict)

                # Store table info in the main dictionary
                db_data[table_name] = {'schema': [dict(col) for col in columns], 'data': table_data}

            conn.close()
            return db_data

        except sqlite3.Error as e:
            print(f'SQLite error: {e}')
            return None
        except Exception as e:
            print(f'Error: {e}')
            return None


if __name__ == '__main__':
    DBLoader.click()
