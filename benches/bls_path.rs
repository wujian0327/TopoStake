use criterion::{black_box, criterion_group, criterion_main, BenchmarkId, Criterion};
use std::time::Duration;
use topostake::blockchain::path::{
    clear_receipt_cache_for_tests, AggregatedSignedPaths, TransactionPaths,
};
use topostake::blockchain::transaction::Transaction;
use topostake::wallet::Wallet;

fn build_completed_path(
    path_len: usize,
    epoch: u64,
) -> (Transaction, TransactionPaths, Vec<Wallet>) {
    clear_receipt_cache_for_tests();
    let wallets: Vec<Wallet> = (0..=path_len).map(|_| Wallet::new()).collect();
    let tx = Transaction::new("bench".to_string(), 0, wallets[0].clone());
    let mut tx_paths = TransactionPaths::new_with_epoch(tx.clone(), epoch);
    for i in 0..path_len {
        assert!(tx_paths.append_outgoing_hop(wallets[i + 1].address.clone(), wallets[i].clone()));
        assert!(tx_paths.complete_pending_hop(wallets[i + 1].clone()));
    }
    (tx, tx_paths, wallets)
}

fn build_pending_hop(epoch: u64) -> (TransactionPaths, Wallet) {
    clear_receipt_cache_for_tests();
    let sender = Wallet::new();
    let receiver = Wallet::new();
    let tx = Transaction::new("bench".to_string(), 0, sender.clone());
    let mut tx_paths = TransactionPaths::new_with_epoch(tx, epoch);
    assert!(tx_paths.append_outgoing_hop(receiver.address.clone(), sender));
    (tx_paths, receiver)
}

fn bls_path_benches(c: &mut Criterion) {
    let quick = std::env::var("CRITERION_QUICK").is_ok();

    let mut single = c.benchmark_group("single hop");
    if quick {
        single.warm_up_time(Duration::from_millis(100));
        single.measurement_time(Duration::from_millis(250));
        single.sample_size(10);
    }

    single.bench_function("sender sign", |b| {
        let sender = Wallet::new();
        let receiver = Wallet::new();
        let tx = Transaction::new("bench".to_string(), 0, sender.clone());
        b.iter(|| {
            let mut tx_paths = TransactionPaths::new_with_epoch(tx.clone(), 1);
            assert!(tx_paths.append_outgoing_hop(receiver.address.clone(), sender.clone()));
        });
    });

    single.bench_function("receiver sign", |b| {
        let (pending, receiver) = build_pending_hop(2);
        b.iter(|| {
            let mut tx_paths = pending.clone();
            assert!(tx_paths.complete_pending_hop(receiver.clone()));
        });
    });
    single.finish();

    let mut group = c.benchmark_group("path length");
    if quick {
        group.warm_up_time(Duration::from_millis(100));
        group.measurement_time(Duration::from_millis(250));
        group.sample_size(10);
    }
    for path_len in [1usize, 2, 4, 8, 16] {
        group.bench_with_input(BenchmarkId::new("sign", path_len), &path_len, |b, len| {
            let wallets: Vec<Wallet> = (0..*len).map(|_| Wallet::new()).collect();
            let messages: Vec<Vec<u8>> = (0..*len)
                .map(|i| format!("bench-message-{i}").into_bytes())
                .collect();
            b.iter(|| {
                for i in 0..*len {
                    let signature = wallets[i].sign_by_bls(messages[i].clone());
                    assert!(!black_box(signature).is_empty());
                }
            });
        });

        group.bench_with_input(BenchmarkId::new("verify", path_len), &path_len, |b, len| {
            let wallets: Vec<Wallet> = (0..*len).map(|_| Wallet::new()).collect();
            let messages: Vec<Vec<u8>> = (0..*len)
                .map(|i| format!("bench-message-{i}").into_bytes())
                .collect();
            let signatures: Vec<String> = wallets
                .iter()
                .zip(messages.iter())
                .map(|(wallet, message)| wallet.sign_by_bls(message.clone()))
                .collect();
            b.iter(|| {
                for i in 0..*len {
                    assert!(Wallet::verify_bls_with_pk(
                        messages[i].clone(),
                        signatures[i].clone(),
                        wallets[i].bls_public_key
                    ));
                }
            });
        });

        group.bench_with_input(
            BenchmarkId::new("aggregation", path_len),
            &path_len,
            |b, len| {
                let (_tx, tx_paths, _wallets) = build_completed_path(*len, 3);
                b.iter(|| {
                    let aggregated =
                        AggregatedSignedPaths::from_transaction_paths(tx_paths.clone());
                    assert!(!aggregated.signature.is_empty());
                });
            },
        );

        group.bench_with_input(
            BenchmarkId::new("aggregate verification", path_len),
            &path_len,
            |b, len| {
                let (tx, tx_paths, wallets) = build_completed_path(*len, 4);
                let proposer = wallets.last().unwrap().address.clone();
                let aggregated = AggregatedSignedPaths::from_transaction_paths(tx_paths);
                b.iter(|| {
                    clear_receipt_cache_for_tests();
                    assert!(aggregated.verify_at_epoch(tx.clone(), proposer.clone(), 4));
                });
            },
        );
    }
    group.finish();
}

criterion_group!(benches, bls_path_benches);
criterion_main!(benches);
