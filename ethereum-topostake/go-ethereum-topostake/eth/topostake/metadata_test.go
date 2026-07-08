package topostake

import (
	"encoding/hex"
	"encoding/json"
	"math/big"
	"sync"
	"testing"

	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/core/rawdb"
	"github.com/ethereum/go-ethereum/core/state"
	"github.com/ethereum/go-ethereum/core/tracing"
	"github.com/ethereum/go-ethereum/core/types"
	"github.com/ethereum/go-ethereum/triedb"
	"github.com/holiman/uint256"
	blst "github.com/supranational/blst/bindings/go"
)

func TestStoreCreatesOriginMetadata(t *testing.T) {
	secret := blst.KeyGen([]byte("topostake prompt14 deterministic test key material"))
	t.Setenv("TOPOSTAKE_RELAY_VALIDATOR_INDEX", "2")
	t.Setenv("TOPOSTAKE_RELAY_PRIVATE_KEY", "0x"+hex.EncodeToString(secret.Serialize()))
	t.Setenv("TOPOSTAKE_CHAIN_ID", "7032030")
	t.Setenv("TOPOSTAKE_RELAY_EPOCH", "7")

	store := NewStoreFromEnv()
	if !store.Enabled() {
		t.Fatal("store should be enabled with validator index and relay key")
	}
	hash := common.HexToHash("0x1234")
	store.EnsureLocalHash(hash)
	batch := store.MetadataBatch([]common.Hash{hash})
	if len(batch) != 1 || len(batch[0]) == 0 {
		t.Fatalf("missing metadata batch: %#v", batch)
	}
	var meta propagationMetadata
	if err := json.Unmarshal(batch[0], &meta); err != nil {
		t.Fatal(err)
	}
	if meta.Domain != Domain {
		t.Fatalf("unexpected domain %q", meta.Domain)
	}
	if meta.ChainID != DefaultChainID {
		t.Fatalf("unexpected chain id %d", meta.ChainID)
	}
	if meta.Epoch != 7 {
		t.Fatalf("unexpected epoch %d", meta.Epoch)
	}
	if meta.TxHash != hash.Hex() {
		t.Fatalf("unexpected tx hash %s", meta.TxHash)
	}
	if meta.OriginRelayValidatorIndex != 2 {
		t.Fatalf("unexpected validator %d", meta.OriginRelayValidatorIndex)
	}
	if meta.OriginRelayAddress != fallbackRelayAddress(2) {
		t.Fatalf("unexpected origin relay address %s", meta.OriginRelayAddress)
	}
	rawSig, err := hex.DecodeString(meta.OriginSignature[2:])
	if err != nil {
		t.Fatal(err)
	}
	sig := new(blst.P1Affine).Uncompress(rawSig)
	pub := new(blst.P2Affine).From(secret)
	if !sig.Verify(true, pub, false, originStatement(DefaultChainID, 7, hash, fallbackRelayAddress(2)), []byte(Domain)) {
		t.Fatal("origin signature did not verify")
	}
}

func TestStoreInjectsDevnetPathEvidence(t *testing.T) {
	type relayEntry struct {
		NodeIndex       uint64 `json:"node_index"`
		ServiceName     string `json:"service_name"`
		ValidatorIndex  uint64 `json:"validator_index"`
		RelayAddress    string `json:"relay_address"`
		PayoutAddress   string `json:"payout_address"`
		RelayPubkey     string `json:"relay_pubkey"`
		RelayPrivateKey string `json:"relay_private_key"`
	}
	registry := struct {
		Relays []relayEntry `json:"relays"`
	}{}
	for i := uint64(0); i < 3; i++ {
		secret := blst.KeyGen([]byte("topostake devnet injected path evidence relay key " + string(rune('0'+i))))
		registry.Relays = append(registry.Relays, relayEntry{
			NodeIndex:       i,
			ServiceName:     serviceNameForNodeIndex(i),
			ValidatorIndex:  i,
			RelayAddress:    fallbackRelayAddress(i),
			PayoutAddress:   fallbackRelayAddress(i + 10),
			RelayPubkey:     "0x" + hex.EncodeToString(new(blst.P2Affine).From(secret).Compress()),
			RelayPrivateKey: "0x" + hex.EncodeToString(secret.Serialize()),
		})
	}
	raw, err := json.Marshal(registry)
	if err != nil {
		t.Fatal(err)
	}
	t.Setenv("TOPOSTAKE_RELAY_PRIVATE_REGISTRY_JSON", string(raw))
	t.Setenv("TOPOSTAKE_CHAIN_ID", "7032030")
	t.Setenv("TOPOSTAKE_RELAY_EPOCH", "7")

	store := NewStoreFromEnv()
	hash := common.HexToHash("0x1234")
	metadata, err := store.InjectPathEvidence(hash, []uint64{0, 1, 2})
	if err != nil {
		t.Fatal(err)
	}
	var meta propagationMetadata
	if err := json.Unmarshal(metadata, &meta); err != nil {
		t.Fatal(err)
	}
	if meta.Status != "devnet_injected" {
		t.Fatalf("unexpected status %q", meta.Status)
	}
	if len(meta.Paths) != 2 {
		t.Fatalf("unexpected path len %d", len(meta.Paths))
	}
	if !store.verifyOrigin(meta) {
		t.Fatal("origin signature did not verify")
	}
	for i := range meta.Paths {
		if !store.verifySender(meta, i) {
			t.Fatalf("sender signature %d did not verify", i)
		}
	}
}

func TestStoreDisabledWithoutRelayKey(t *testing.T) {
	t.Setenv("TOPOSTAKE_RELAY_VALIDATOR_INDEX", "2")
	t.Setenv("TOPOSTAKE_RELAY_PRIVATE_KEY", "")
	store := NewStoreFromEnv()
	if store.Enabled() {
		t.Fatal("store should stay disabled without relay private key")
	}
}

func TestFeeRecipientEscrowSwitch(t *testing.T) {
	coinbase := common.HexToAddress("0x000000000000000000000000000000000000c0de")
	if got := FeeRecipient(coinbase); got != coinbase {
		t.Fatalf("fee recipient should default to coinbase: %s", got)
	}
	t.Setenv("TOPOSTAKE_FEE_ESCROW", "1")
	if got := FeeRecipient(coinbase); got != FeeEscrowAddress {
		t.Fatalf("fee recipient should be escrow address: %s", got)
	}
}

func TestStoreSelectsRelayKeyFromPrivateRegistry(t *testing.T) {
	secret0 := blst.KeyGen([]byte("topostake prompt14 private registry key 0"))
	secret1 := blst.KeyGen([]byte("topostake prompt14 private registry key 1"))
	registry := map[string]any{
		"relays": []map[string]any{
			{
				"node_index":        uint64(0),
				"service_name":      "el-1-geth-lighthouse",
				"validator_index":   uint64(0),
				"relay_address":     fallbackRelayAddress(0),
				"relay_pubkey":      "0x" + hex.EncodeToString(new(blst.P2Affine).From(secret0).Compress()),
				"relay_private_key": "0x" + hex.EncodeToString(secret0.Serialize()),
			},
			{
				"node_index":        uint64(1),
				"service_name":      "el-2-geth-lighthouse",
				"validator_index":   uint64(1),
				"relay_address":     fallbackRelayAddress(1),
				"relay_pubkey":      "0x" + hex.EncodeToString(new(blst.P2Affine).From(secret1).Compress()),
				"relay_private_key": "0x" + hex.EncodeToString(secret1.Serialize()),
			},
		},
	}
	raw, err := json.Marshal(registry)
	if err != nil {
		t.Fatal(err)
	}
	t.Setenv("TOPOSTAKE_RELAY_PRIVATE_REGISTRY_JSON", string(raw))
	t.Setenv("TOPOSTAKE_RELAY_NODE_INDEX", "1")

	store := NewStoreFromEnv()
	if !store.Enabled() {
		t.Fatal("store should be enabled from private registry")
	}
	if store.localValidator != 1 {
		t.Fatalf("unexpected local validator %d", store.localValidator)
	}
	hash := common.HexToHash("0xabcd")
	store.EnsureLocalHash(hash)
	batch := store.MetadataBatch([]common.Hash{hash})
	if len(batch) != 1 || len(batch[0]) == 0 {
		t.Fatalf("missing metadata batch: %#v", batch)
	}
	var meta propagationMetadata
	if err := json.Unmarshal(batch[0], &meta); err != nil {
		t.Fatal(err)
	}
	if meta.OriginRelayValidatorIndex != 1 {
		t.Fatalf("unexpected origin validator %d", meta.OriginRelayValidatorIndex)
	}
	if meta.OriginRelayAddress != fallbackRelayAddress(1) {
		t.Fatalf("unexpected origin address %s", meta.OriginRelayAddress)
	}
}

func TestStoreMapsPeerByRemoteAddress(t *testing.T) {
	store := testStore(0, blst.KeyGen([]byte("topostake prompt14 address map local")))
	store.addrs["172.16.0.22"] = relayIdentity{ValidatorIndex: 2, Address: fallbackRelayAddress(2)}
	validator, ok := store.peerValidator("", "172.16.0.22:30303")
	if !ok || validator != 2 {
		t.Fatalf("unexpected address mapping validator=%d ok=%v", validator, ok)
	}
}

func TestStoreCompletesSignedEdge(t *testing.T) {
	senderKey := blst.KeyGen([]byte("topostake prompt14 sender key material"))
	receiverKey := blst.KeyGen([]byte("topostake prompt14 receiver key material"))
	sender := testStore(0, senderKey)
	receiver := testStore(1, receiverKey)
	sender.peers["peer-b"] = relayIdentity{ValidatorIndex: 1, Address: fallbackRelayAddress(1)}
	pub0 := new(blst.P2Affine).From(senderKey).Compress()
	pub1 := new(blst.P2Affine).From(receiverKey).Compress()
	sender.relayPubkeys[0] = pub0
	sender.relayPubkeys[1] = pub1
	receiver.relayPubkeys[0] = pub0
	receiver.relayPubkeys[1] = pub1

	hash := common.HexToHash("0x4567")
	sender.EnsureLocalHash(hash)
	out := sender.MetadataBatchForPeer([]common.Hash{hash}, "peer-b")
	if len(out) != 1 || len(out[0]) == 0 {
		t.Fatalf("missing outgoing metadata: %#v", out)
	}
	var pending propagationMetadata
	if err := json.Unmarshal(out[0], &pending); err != nil {
		t.Fatal(err)
	}
	if len(pending.Paths) != 1 {
		t.Fatalf("expected one pending edge, got %d", len(pending.Paths))
	}
	if pending.Paths[0].From != 0 || pending.Paths[0].To != 1 {
		t.Fatalf("unexpected edge %#v", pending.Paths[0])
	}
	if pending.Paths[0].FromAddress != fallbackRelayAddress(0) || pending.Paths[0].ToAddress != fallbackRelayAddress(1) {
		t.Fatalf("unexpected edge addresses %#v", pending.Paths[0])
	}
	if pending.Paths[0].ReceiverSignature != "" {
		t.Fatal("sender should not fill receiver signature")
	}

	receiver.RecordInbound([]common.Hash{hash}, out)
	stored := receiver.MetadataBatch([]common.Hash{hash})
	if len(stored) != 1 || len(stored[0]) == 0 {
		t.Fatalf("receiver did not store metadata: %#v", stored)
	}
	var completed propagationMetadata
	if err := json.Unmarshal(stored[0], &completed); err != nil {
		t.Fatal(err)
	}
	if completed.Status != "edge_received" {
		t.Fatalf("unexpected status %q", completed.Status)
	}
	if len(completed.Paths) != 1 || completed.Paths[0].ReceiverSignature == "" {
		t.Fatalf("receiver signature was not completed: %#v", completed.Paths)
	}
	if !receiver.verifySender(completed, 0) {
		t.Fatal("completed metadata sender signature did not verify")
	}
}

func TestStoreMetadataBatchForPeerIsConcurrentSafe(t *testing.T) {
	senderKey := blst.KeyGen([]byte("topostake concurrent sender key material"))
	receiverKey := blst.KeyGen([]byte("topostake concurrent receiver key material"))
	store := testStore(0, senderKey)
	store.peers["peer-b"] = relayIdentity{ValidatorIndex: 1, Address: fallbackRelayAddress(1)}
	store.relayPubkeys[0] = new(blst.P2Affine).From(senderKey).Compress()
	store.relayPubkeys[1] = new(blst.P2Affine).From(receiverKey).Compress()

	hashes := make([]common.Hash, 32)
	for i := range hashes {
		hashes[i] = common.BigToHash(new(big.Int).SetUint64(uint64(i + 1)))
		store.EnsureLocalHash(hashes[i])
	}

	var wg sync.WaitGroup
	for worker := 0; worker < 32; worker++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for i := 0; i < 128; i++ {
				batch := store.MetadataBatchForPeer(hashes, "peer-b")
				if len(batch) != len(hashes) {
					t.Errorf("unexpected batch length %d", len(batch))
					return
				}
			}
		}()
	}
	wg.Wait()
}

func TestStoreRejectsBadSenderSignature(t *testing.T) {
	senderKey := blst.KeyGen([]byte("topostake prompt14 sender key material bad"))
	receiverKey := blst.KeyGen([]byte("topostake prompt14 receiver key material bad"))
	sender := testStore(0, senderKey)
	receiver := testStore(1, receiverKey)
	sender.peers["peer-b"] = relayIdentity{ValidatorIndex: 1, Address: fallbackRelayAddress(1)}
	pub0 := new(blst.P2Affine).From(senderKey).Compress()
	pub1 := new(blst.P2Affine).From(receiverKey).Compress()
	sender.relayPubkeys[0] = pub0
	sender.relayPubkeys[1] = pub1
	receiver.relayPubkeys[0] = pub0
	receiver.relayPubkeys[1] = pub1

	hash := common.HexToHash("0x7890")
	sender.EnsureLocalHash(hash)
	out := sender.MetadataBatchForPeer([]common.Hash{hash}, "peer-b")
	var meta propagationMetadata
	if err := json.Unmarshal(out[0], &meta); err != nil {
		t.Fatal(err)
	}
	meta.Paths[0].SenderSignature = "0x00"
	tampered, err := json.Marshal(meta)
	if err != nil {
		t.Fatal(err)
	}
	receiver.RecordInbound([]common.Hash{hash}, []TxMetadata{tampered})
	stored := receiver.MetadataBatch([]common.Hash{hash})
	if len(stored) != 1 || len(stored[0]) != 0 {
		t.Fatalf("receiver stored tampered metadata: %#v", stored)
	}
}

func TestStoreRecordsBlockEvidence(t *testing.T) {
	secret := blst.KeyGen([]byte("topostake prompt14 block evidence key"))
	store := testStore(0, secret)
	tx := types.NewTx(&types.LegacyTx{
		Nonce: 1,
		To:    &common.Address{0x42},
		Gas:   21_000,
	})
	hash := tx.Hash()
	store.EnsureLocalHash(hash)

	blockHash := common.HexToHash("0xabcdef")
	store.RecordBlockEvidence(blockHash, 12, types.Transactions{tx})
	evidence, ok := store.BlockEvidence(blockHash)
	if !ok {
		t.Fatal("missing block evidence")
	}
	if evidence.BlockHash != blockHash.Hex() || evidence.BlockNumber != 12 {
		t.Fatalf("unexpected block evidence header: %#v", evidence)
	}
	if evidence.TxCount != 1 || evidence.EvidenceCount != 1 {
		t.Fatalf("unexpected evidence counts: %#v", evidence)
	}
	if evidence.EvidenceRoot == "" {
		t.Fatal("missing block evidence root")
	}
	if evidence.AggregateSignature == "" {
		t.Fatal("missing block aggregate signature")
	}
	if evidence.AggregateSignatureCount != 1 {
		t.Fatalf("unexpected aggregate signature count %d", evidence.AggregateSignatureCount)
	}
	if len(evidence.Transactions) != 1 || evidence.Transactions[0].TxHash != hash.Hex() {
		t.Fatalf("unexpected tx evidence: %#v", evidence.Transactions)
	}
	var meta propagationMetadata
	if err := json.Unmarshal(evidence.Transactions[0].Metadata, &meta); err != nil {
		t.Fatal(err)
	}
	if meta.TxHash != hash.Hex() {
		t.Fatalf("unexpected metadata tx hash %s", meta.TxHash)
	}
}

func TestStoreRecordsCommittedFeeInput(t *testing.T) {
	t.Setenv("TOPOSTAKE_FEE_ESCROW", "1")
	secret := blst.KeyGen([]byte("topostake prompt23 fee evidence key"))
	store := testStore(0, secret)
	tx := types.NewTx(&types.LegacyTx{
		Nonce:    1,
		To:       &common.Address{0x42},
		Gas:      21_000,
		GasPrice: big.NewInt(3),
	})
	hash := tx.Hash()
	store.EnsureLocalHash(hash)

	blockHash := common.HexToHash("0xfee")
	receipt := &types.Receipt{GasUsed: 21_000}
	coinbase := common.HexToAddress("0x000000000000000000000000000000000000c0de")
	store.RecordBlockEvidenceWithReceipts(blockHash, 13, types.Transactions{tx}, types.Receipts{receipt}, nil, coinbase)
	evidence, ok := store.BlockEvidence(blockHash)
	if !ok || len(evidence.Transactions) != 1 {
		t.Fatalf("missing fee evidence: %#v", evidence)
	}
	txEvidence := evidence.Transactions[0]
	if txEvidence.GasUsed != 21_000 {
		t.Fatalf("unexpected gas used %d", txEvidence.GasUsed)
	}
	if txEvidence.EffectiveGasTipWei != "3" {
		t.Fatalf("unexpected effective tip %q", txEvidence.EffectiveGasTipWei)
	}
	if txEvidence.PriorityFeeWei != "63000" {
		t.Fatalf("unexpected priority fee %q", txEvidence.PriorityFeeWei)
	}
	if txEvidence.FeeRecipient != coinbase.Hex() {
		t.Fatalf("unexpected fee recipient %q", txEvidence.FeeRecipient)
	}
	if txEvidence.EscrowRecipient != FeeEscrowAddress.Hex() {
		t.Fatalf("unexpected escrow recipient %q", txEvidence.EscrowRecipient)
	}
}

func TestStoreAppliesSubmittedSettlementOnce(t *testing.T) {
	t.Setenv("TOPOSTAKE_FEE_ESCROW", "1")
	t.Setenv("TOPOSTAKE_SETTLEMENT_MUTATION", "1")
	store := testStore(0, blst.KeyGen([]byte("topostake prompt23 settlement execution key")))
	payout := common.HexToAddress("0x000000000000000000000000000000000000beef")
	records, err := store.SubmitSettlement(SettlementPayload{
		Domain:         "TOPOSTAKE_FEE_SETTLEMENT_V1",
		FinalizedEpoch: 2,
		Epoch:          0,
		Records: []SettlementRecord{
			{
				Epoch:          0,
				Role:           "proposer",
				ValidatorIndex: 1,
				PayoutAddress:  payout.Hex(),
				AmountWei:      "700",
			},
			{
				Epoch:     0,
				Role:      "burned",
				AmountWei: "300",
			},
		},
	})
	if err != nil {
		t.Fatal(err)
	}
	if records != 2 {
		t.Fatalf("unexpected record count %d", records)
	}
	memoryDB := rawdb.NewMemoryDatabase()
	stateDB, err := state.New(types.EmptyRootHash, state.NewDatabase(triedb.NewDatabase(memoryDB, nil), nil))
	if err != nil {
		t.Fatal(err)
	}
	stateDB.AddBalance(FeeEscrowAddress, uint256.NewInt(2_000), tracing.BalanceChangeUnspecified)
	if applied := store.ApplyCommittedSettlement(common.Hash{}, stateDB); applied != 0 {
		t.Fatalf("zero root should not apply settlement: %d", applied)
	}
	root := store.PendingSettlementRoot()
	if root == (common.Hash{}) {
		t.Fatal("expected pending settlement root")
	}
	extra := SettlementExtraFromRoot(root)
	if got := SettlementRootFromExtra(extra); got != root {
		t.Fatalf("extra roundtrip mismatch %s want %s", got, root)
	}
	if applied := store.ApplyCommittedSettlement(root, stateDB); applied != 1 {
		t.Fatalf("expected one applied settlement, got %d", applied)
	}
	if got, want := stateDB.GetBalance(FeeEscrowAddress), uint256.NewInt(1_000); !got.Eq(want) {
		t.Fatalf("unexpected escrow balance %s want %s", got, want)
	}
	if got, want := stateDB.GetBalance(payout), uint256.NewInt(700); !got.Eq(want) {
		t.Fatalf("unexpected payout balance %s want %s", got, want)
	}
	if applied := store.ApplyCommittedSettlement(root, stateDB); applied != 0 {
		t.Fatalf("settlement should be idempotent, applied again: %d", applied)
	}
	if got, want := stateDB.GetBalance(FeeEscrowAddress), uint256.NewInt(1_000); !got.Eq(want) {
		t.Fatalf("unexpected escrow balance after duplicate apply %s want %s", got, want)
	}
	if got, want := stateDB.GetBalance(payout), uint256.NewInt(700); !got.Eq(want) {
		t.Fatalf("unexpected payout balance after duplicate apply %s want %s", got, want)
	}

	blockRecords := store.SettlementRecordsForRoot(root)
	replayStateDB, err := state.New(types.EmptyRootHash, state.NewDatabase(triedb.NewDatabase(rawdb.NewMemoryDatabase(), nil), nil))
	if err != nil {
		t.Fatal(err)
	}
	replayStateDB.AddBalance(FeeEscrowAddress, uint256.NewInt(2_000), tracing.BalanceChangeUnspecified)
	applied, err := store.ApplyCommittedSettlementRecords(root, blockRecords, replayStateDB, true)
	if err != nil {
		t.Fatal(err)
	}
	if applied != 1 {
		t.Fatalf("block-carried settlement records should replay despite local executed marker, got %d", applied)
	}
	if got, want := replayStateDB.GetBalance(FeeEscrowAddress), uint256.NewInt(1_000); !got.Eq(want) {
		t.Fatalf("unexpected replay escrow balance %s want %s", got, want)
	}
	if got, want := replayStateDB.GetBalance(payout), uint256.NewInt(700); !got.Eq(want) {
		t.Fatalf("unexpected replay payout balance %s want %s", got, want)
	}
}

func TestStoreSettlementMutationDefaultsToNoop(t *testing.T) {
	t.Setenv("TOPOSTAKE_FEE_ESCROW", "1")
	store := testStore(0, blst.KeyGen([]byte("topostake prompt23 settlement noop key")))
	payout := common.HexToAddress("0x000000000000000000000000000000000000babe")
	_, err := store.SubmitSettlement(SettlementPayload{
		Domain:         "TOPOSTAKE_FEE_SETTLEMENT_V1",
		FinalizedEpoch: 2,
		Epoch:          0,
		Records: []SettlementRecord{
			{
				Epoch:          0,
				Role:           "proposer",
				ValidatorIndex: 1,
				PayoutAddress:  payout.Hex(),
				AmountWei:      "700",
			},
		},
	})
	if err != nil {
		t.Fatal(err)
	}
	memoryDB := rawdb.NewMemoryDatabase()
	stateDB, err := state.New(types.EmptyRootHash, state.NewDatabase(triedb.NewDatabase(memoryDB, nil), nil))
	if err != nil {
		t.Fatal(err)
	}
	stateDB.AddBalance(FeeEscrowAddress, uint256.NewInt(2_000), tracing.BalanceChangeUnspecified)
	root := store.PendingSettlementRoot()
	if root == (common.Hash{}) {
		t.Fatal("expected pending settlement root")
	}
	if applied := store.ApplyCommittedSettlement(root, stateDB); applied != 0 {
		t.Fatalf("settlement mutation should default to noop, applied %d", applied)
	}
	if got, want := stateDB.GetBalance(FeeEscrowAddress), uint256.NewInt(2_000); !got.Eq(want) {
		t.Fatalf("unexpected escrow balance %s want %s", got, want)
	}
	if got, want := stateDB.GetBalance(payout), uint256.NewInt(0); !got.Eq(want) {
		t.Fatalf("unexpected payout balance %s want %s", got, want)
	}
}

func TestApplyCommittedSettlementRecordsFallsBackToLocalStore(t *testing.T) {
	t.Setenv("TOPOSTAKE_FEE_ESCROW", "1")
	t.Setenv("TOPOSTAKE_SETTLEMENT_MUTATION", "1")
	store := testStore(0, blst.KeyGen([]byte("topostake prompt43 local settlement fallback key")))
	payout := common.HexToAddress("0x000000000000000000000000000000000000cafe")
	_, err := store.SubmitSettlement(SettlementPayload{
		Domain:         "TOPOSTAKE_FEE_SETTLEMENT_V1",
		FinalizedEpoch: 3,
		Epoch:          1,
		Records: []SettlementRecord{
			{
				Epoch:          1,
				Role:           "proposer",
				ValidatorIndex: 2,
				PayoutAddress:  payout.Hex(),
				AmountWei:      "900",
			},
		},
	})
	if err != nil {
		t.Fatal(err)
	}
	memoryDB := rawdb.NewMemoryDatabase()
	stateDB, err := state.New(types.EmptyRootHash, state.NewDatabase(triedb.NewDatabase(memoryDB, nil), nil))
	if err != nil {
		t.Fatal(err)
	}
	stateDB.AddBalance(FeeEscrowAddress, uint256.NewInt(1_000), tracing.BalanceChangeUnspecified)
	root := store.PendingSettlementRoot()
	if root == (common.Hash{}) {
		t.Fatal("expected pending settlement root")
	}
	applied, err := store.ApplyCommittedSettlementRecords(root, nil, stateDB, true)
	if err != nil {
		t.Fatal(err)
	}
	if applied != 1 {
		t.Fatalf("expected fallback settlement apply, got %d", applied)
	}
	if got, want := stateDB.GetBalance(FeeEscrowAddress), uint256.NewInt(100); !got.Eq(want) {
		t.Fatalf("unexpected escrow balance %s want %s", got, want)
	}
	if got, want := stateDB.GetBalance(payout), uint256.NewInt(900); !got.Eq(want) {
		t.Fatalf("unexpected payout balance %s want %s", got, want)
	}
}

func TestApplyCommittedSettlementRecordsErrorsWhenMissingEverywhere(t *testing.T) {
	t.Setenv("TOPOSTAKE_FEE_ESCROW", "1")
	t.Setenv("TOPOSTAKE_SETTLEMENT_MUTATION", "1")
	store := testStore(0, blst.KeyGen([]byte("topostake prompt43 missing settlement records key")))
	memoryDB := rawdb.NewMemoryDatabase()
	stateDB, err := state.New(types.EmptyRootHash, state.NewDatabase(triedb.NewDatabase(memoryDB, nil), nil))
	if err != nil {
		t.Fatal(err)
	}
	_, err = store.ApplyCommittedSettlementRecords(common.HexToHash("0x1234"), nil, stateDB, true)
	if err == nil {
		t.Fatal("expected missing settlement records error")
	}
}

func testStore(validator uint64, secret *blst.SecretKey) *Store {
	store := &Store{
		enabled:               true,
		localValidator:        validator,
		chainID:               DefaultChainID,
		maxBytes:              DefaultMaxBytes,
		secret:                secret,
		publicKey:             new(blst.P2Affine).From(secret).Compress(),
		metadata:              make(map[common.Hash]TxMetadata),
		relayPubkeys:          make(map[uint64][]byte),
		relayPubkeysByAddress: make(map[string][]byte),
		validatorAddresses:    make(map[uint64]string),
		addressValidators:     make(map[string]uint64),
		peers:                 make(map[string]relayIdentity),
		addrs:                 make(map[string]relayIdentity),
		blocks:                make(map[common.Hash]*BlockEvidence),
		settlements:           make(map[string]*SettlementPayload),
		settlementsByRoot:     make(map[common.Hash]*SettlementPayload),
		settlementRootByKey:   make(map[string]common.Hash),
		executedSettlements:   make(map[string]bool),
	}
	store.epoch.Store(7)
	store.localAddress = store.registerRelayIdentity(validator, fallbackRelayAddress(validator), store.publicKey)
	return store
}
