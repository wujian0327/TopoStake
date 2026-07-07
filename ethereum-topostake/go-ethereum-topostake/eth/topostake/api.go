// Copyright 2026 The go-ethereum Authors
// This file is part of the go-ethereum library.

package topostake

import (
	"context"
	"errors"

	"github.com/ethereum/go-ethereum/common"
)

var errEvidenceNotFound = errors.New("topostake block evidence not found")

type API struct {
	store *Store
}

func NewAPI(store *Store) *API {
	return &API{store: store}
}

func (api *API) GetBlockEvidence(ctx context.Context, hash common.Hash) (*BlockEvidence, error) {
	evidence, ok := api.store.BlockEvidence(hash)
	if !ok {
		return nil, errEvidenceNotFound
	}
	return evidence, nil
}

func (api *API) InjectPathEvidence(ctx context.Context, hash common.Hash, validators []uint64) (map[string]any, error) {
	metadata, err := api.store.InjectPathEvidence(hash, validators)
	if err != nil {
		return nil, err
	}
	return map[string]any{
		"accepted":   true,
		"tx_hash":    hash.Hex(),
		"validators": validators,
		"metadata":   metadata,
	}, nil
}

func (api *API) SubmitSettlement(ctx context.Context, payload SettlementPayload) (map[string]any, error) {
	records, err := api.store.SubmitSettlement(payload)
	if err != nil {
		return nil, err
	}
	root := api.store.SettlementRoot(payload.FinalizedEpoch, payload.Epoch)
	return map[string]any{
		"accepted":        true,
		"epoch":           payload.Epoch,
		"finalized_epoch": payload.FinalizedEpoch,
		"records":         records,
		"settlement_root": root.Hex(),
	}, nil
}
