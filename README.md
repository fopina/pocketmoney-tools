# PocketMoney Tools

Random tools for [PocketMoney](https://apps.apple.com/us/app/pocketmoney/id1281288102) databases

## Dashboards

Pushing transactions to `(OpenSearch|PostgreSQL|?)` and visualizing it with `(OpenSearch Dashboards|Grafana|?)`

### Usage

1. Backup DB to iCloud (or Dropbox or whatever)
1. Run `./refresh_from_icloud.py`
    * This looks for a backup in `~/Library/Mobile\ Documents/iCloud\~com\~pocketmoney\~app/Synchronization/...` 
1. Run `utils/db_loader.py pocketmoney.pmdb`
    * This converts the sqlite DB to JSON

Now choose your stack:
* OpenSearch + OpenSearch Dashboards - [opensearch](opensearch/README.md)
* PostgreSQL + Grafana - [postgres](...)


> To use the demo JSON file:
> * Jump straight into the stack (of your choice) README, no need for any of these steps
> 
> OpenSearch:
> ![Demo dashboard - OpenSearch](samples/demo.png)
> PostgreSQL + Grafana:
> ![Demo dashboard - Grafana](samples/demo_pg.png)

## Reconciliation

Reconcile PocketMoney transactions with a CSV statement from other source (eg, *bank*)

Flags allow specifying which columns contain the required info in the CSV

```
$ reconciliation/reconcile.py card_transactions_record_20250611_105312.csv -a 3 --account mybank
(PocketTransaction) 2025-06-11 Saúde / Saude -52.47
(Transaction) 2025-06-10 Crv*Restaurante El Cap -33.2
(Transaction) 2025-06-10 Crv*Q H Centro Leon Le -17.6
(Transaction) 2025-06-10 Crv*Bp Combatentes Por -19.47
(Transaction) 2025-06-10 Crv*Albany Leon Esp -3.6
(Transaction) 2025-06-09 Crv*La Vespa 50 Leon E -50.3
(Transaction) 2025-06-09 Crv*Cedipsa Es Melgar -71.77
(PocketTransaction) 2025-06-08 MIA / MIA -19.4
(Transaction) 2025-06-08 Crv*Bar Animals Ripagaina -115.6
(Transaction) 2025-06-07 EUR Deposit 999.0
...
```