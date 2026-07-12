// Copyright 2026 The go-ethereum Authors
// This file is part of the go-ethereum library.

package topostake

import (
	"context"
	"testing"

	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/rpc"
)

func TestTransactionFirstSeenBatchRPC(t *testing.T) {
	store := &Store{}
	hash := common.HexToHash("0x1234")
	store.ObserveTransactionArrival(hash)

	server := rpc.NewServer()
	if err := server.RegisterName("topostake", NewAPI(store)); err != nil {
		t.Fatal(err)
	}
	client := rpc.DialInProc(server)
	defer client.Close()

	var result map[string]int64
	if err := client.CallContext(
		context.Background(),
		&result,
		"topostake_getTransactionFirstSeenBatch",
		[]common.Hash{hash},
	); err != nil {
		t.Fatal(err)
	}
	if result[hash.Hex()] <= 0 {
		t.Fatalf("missing first-seen timestamp for %s: %#v", hash, result)
	}
}
