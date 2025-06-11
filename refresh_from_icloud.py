#!/usr/bin/env python3

import tempfile
import zipfile
from pathlib import Path

import classyclick
import click


@classyclick.command()
class RefreshFromiCloud:
    icloud_dir: Path = classyclick.Option(
        default=Path.home() / 'Library/Mobile Documents/iCloud~com~pocketmoney~app/Synchronization/',
        help='Path to the PocketMoney iCloud Mobile Documents directory',
    )
    output: Path = classyclick.Option(default=Path.cwd() / 'pocketmoney.pmdb', help='Path to the output file')

    def __call__(self):
        zipfiles = list(self.icloud_dir.glob('*.zip'))
        if not zipfiles:
            raise click.ClickException('No zip files found in the iCloud directory')
        if len(zipfiles) > 1:
            click.echo(f'Found {len(zipfiles)} zip files in the iCloud directory. Please select one:')
            for i, zipf in enumerate(zipfiles):
                click.echo(f'> {i}: {zipf.name}')
            zipf = zipfiles[int(click.prompt('> ', type=click.IntRange(0, len(zipfiles) - 1)))]
        else:
            zipf = zipfiles[0]

        with zipfile.ZipFile(zipf) as zf:
            contents = zf.namelist()
            pmdb_files = [f for f in contents if f.endswith('.pmdb')]

            if not pmdb_files:
                raise click.ClickException('No .pmdb file found in the zip archive')
            if len(pmdb_files) > 1:
                raise click.ClickException('Multiple .pmdb files found in the zip archive')

            pmdb_file = pmdb_files[0]
            with tempfile.TemporaryDirectory() as temp_dir:
                zf.extract(pmdb_file, temp_dir)
                (Path(temp_dir) / pmdb_file).rename(self.output)
            click.echo(f'Extracted {pmdb_file} to {self.output}')


if __name__ == '__main__':
    RefreshFromiCloud.click()
