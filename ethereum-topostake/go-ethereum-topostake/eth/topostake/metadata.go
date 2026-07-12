// Copyright 2026 The go-ethereum Authors
// This file is part of the go-ethereum library.

package topostake

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"math/big"
	"net"
	"os"
	"sort"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/core/state"
	"github.com/ethereum/go-ethereum/core/tracing"
	"github.com/ethereum/go-ethereum/core/types"
	"github.com/ethereum/go-ethereum/metrics"
	"github.com/holiman/uint256"
	blst "github.com/supranational/blst/bindings/go"
)

const (
	Domain          = "TOPOSTAKE_TX_PATH_V1"
	DefaultChainID  = uint64(7_032_030)
	DefaultMaxBytes = 64 * 1024

	serviceLookupTimeout = 75 * time.Millisecond
)

var (
	FeeEscrowAddress = common.HexToAddress("0x0000000000000000000000000000000000705000")

	defaultStoreOnce sync.Once
	defaultStore     *Store

	txMetadataCreatedMeter   = metrics.NewRegisteredMeter("topostake/tx/metadata/created", nil)
	txMetadataForwardMeter   = metrics.NewRegisteredMeter("topostake/tx/metadata/forwarded", nil)
	txMetadataReceivedMeter  = metrics.NewRegisteredMeter("topostake/tx/metadata/received", nil)
	txMetadataSignedOrigin   = metrics.NewRegisteredMeter("topostake/tx/metadata/signed/origin", nil)
	txMetadataSignedSender   = metrics.NewRegisteredMeter("topostake/tx/metadata/signed/sender", nil)
	txMetadataSignedRecv     = metrics.NewRegisteredMeter("topostake/tx/metadata/signed/receiver", nil)
	txMetadataVerifiedOK     = metrics.NewRegisteredMeter("topostake/tx/metadata/verified/sender/ok", nil)
	txMetadataVerifiedFail   = metrics.NewRegisteredMeter("topostake/tx/metadata/verified/sender/fail", nil)
	txMetadataInvalidMeter   = metrics.NewRegisteredMeter("topostake/tx/metadata/invalid", nil)
	txMetadataBytesMeter     = metrics.NewRegisteredMeter("topostake/tx/metadata/bytes", nil)
	txPathLengthGauge        = metrics.NewRegisteredGauge("topostake/tx/path/length", nil)
	blockEvidenceMeter       = metrics.NewRegisteredMeter("topostake/block/evidence/recorded", nil)
	blockEvidenceTxGauge     = metrics.NewRegisteredGauge("topostake/block/evidence/txs", nil)
	settlementSubmittedMeter = metrics.NewRegisteredMeter("topostake/settlement/submitted", nil)
	settlementAppliedMeter   = metrics.NewRegisteredMeter("topostake/settlement/applied", nil)
	settlementSkippedMeter   = metrics.NewRegisteredMeter("topostake/settlement/skipped", nil)
)

func FeeEscrowEnabled() bool {
	switch strings.ToLower(strings.TrimSpace(os.Getenv("TOPOSTAKE_FEE_ESCROW"))) {
	case "1", "true", "yes", "on", "escrow":
		return true
	default:
		return false
	}
}

func SettlementMutationEnabled() bool {
	switch strings.ToLower(strings.TrimSpace(os.Getenv("TOPOSTAKE_SETTLEMENT_MUTATION"))) {
	case "1", "true", "yes", "on":
		return true
	default:
		return false
	}
}

func FeeRecipient(coinbase common.Address) common.Address {
	if FeeEscrowEnabled() {
		return FeeEscrowAddress
	}
	return coinbase
}

// TxMetadata is the devnet-only TopoStake transaction propagation sidecar.
// It is intentionally not part of the signed Ethereum transaction bytes.
type TxMetadata []byte

type Store struct {
	lock                  sync.RWMutex
	enabled               bool
	localValidator        uint64
	localAddress          string
	chainID               uint64
	epoch                 atomic.Uint64
	maxBytes              int
	secret                *blst.SecretKey
	publicKey             []byte
	metadata              map[common.Hash]TxMetadata
	relayPubkeys          map[uint64][]byte
	relayPubkeysByAddress map[string][]byte
	validatorAddresses    map[uint64]string
	addressValidators     map[string]uint64
	peers                 map[string]relayIdentity
	addrs                 map[string]relayIdentity
	serviceIdentities     map[string]relayIdentity
	blocks                map[common.Hash]*BlockEvidence
	settlements           map[string]*SettlementPayload
	settlementsByRoot     map[common.Hash]*SettlementPayload
	settlementRootByKey   map[string]common.Hash
	executedSettlements   map[string]bool
	settlementOrder       []string
}

type relayIdentity struct {
	ValidatorIndex uint64
	Address        string
}

type BlockEvidence struct {
	BlockHash               string                     `json:"block_hash"`
	BlockNumber             uint64                     `json:"block_number"`
	TxCount                 int                        `json:"tx_count"`
	EvidenceCount           int                        `json:"evidence_count"`
	EvidenceRoot            string                     `json:"evidence_root,omitempty"`
	AggregateSignature      string                     `json:"aggregate_signature,omitempty"`
	AggregateSignatureCount int                        `json:"aggregate_signature_count,omitempty"`
	RecordedUnixMillis      int64                      `json:"recorded_unix_millis"`
	Transactions            []BlockTransactionEvidence `json:"transactions"`
}

type BlockTransactionEvidence struct {
	Index                   int             `json:"index"`
	TxHash                  string          `json:"tx_hash"`
	GasUsed                 uint64          `json:"gas_used,omitempty"`
	EffectiveGasTipWei      string          `json:"effective_gas_tip_wei,omitempty"`
	PriorityFeeWei          string          `json:"priority_fee_wei,omitempty"`
	BaseFeeWei              string          `json:"base_fee_wei,omitempty"`
	IrrecoverableCostWei    string          `json:"irrecoverable_cost_wei,omitempty"`
	FeeRecipient            string          `json:"fee_recipient,omitempty"`
	EscrowRecipient         string          `json:"escrow_recipient,omitempty"`
	Metadata                json.RawMessage `json:"metadata"`
}

type SettlementPayload struct {
	Domain         string             `json:"domain"`
	FinalizedEpoch uint64             `json:"finalized_epoch"`
	Epoch          uint64             `json:"epoch"`
	Records        []SettlementRecord `json:"records"`
}

type SettlementRecord struct {
	ID             string `json:"id"`
	Epoch          uint64 `json:"epoch"`
	Role           string `json:"role"`
	ValidatorIndex uint64 `json:"validator_index,omitempty"`
	PayoutAddress  string `json:"payout_address,omitempty"`
	AmountWei      string `json:"amount_wei"`
}

type propagationMetadata struct {
	Version                   uint64     `json:"version"`
	Domain                    string     `json:"domain"`
	ChainID                   uint64     `json:"chain_id"`
	Epoch                     uint64     `json:"epoch"`
	TxHash                    string     `json:"tx_hash"`
	OriginRelayAddress        string     `json:"origin_relay_address"`
	OriginRelayValidatorIndex uint64     `json:"origin_relay_validator_index"`
	OriginRelayPubkey         string     `json:"origin_relay_pubkey"`
	OriginSignature           string     `json:"origin_signature"`
	Paths                     []pathEdge `json:"paths"`
	Status                    string     `json:"status"`
	CreatedUnixMillis         int64      `json:"created_unix_millis"`
}

type pathEdge struct {
	From              uint64 `json:"from"`
	To                uint64 `json:"to"`
	FromAddress       string `json:"from_address"`
	ToAddress         string `json:"to_address"`
	Prefix            string `json:"prefix"`
	SenderSignature   string `json:"sender_signature"`
	ReceiverSignature string `json:"receiver_signature,omitempty"`
}

type blockSignatureRecord struct {
	signer    string
	statement []byte
	signature []byte
}

type relayRegistryFile struct {
	Relays []struct {
		NodeIndex      uint64 `json:"node_index"`
		ServiceName    string `json:"service_name"`
		ValidatorIndex uint64 `json:"validator_index"`
		RelayAddress   string `json:"relay_address"`
		PayoutAddress  string `json:"payout_address"`
		RelayPubkey    string `json:"relay_pubkey"`
	} `json:"relays"`
}

type privateRelayRegistryFile struct {
	Relays []struct {
		NodeIndex       uint64 `json:"node_index"`
		ServiceName     string `json:"service_name"`
		ValidatorIndex  uint64 `json:"validator_index"`
		RelayAddress    string `json:"relay_address"`
		PayoutAddress   string `json:"payout_address"`
		RelayPubkey     string `json:"relay_pubkey"`
		RelayPrivateKey string `json:"relay_private_key"`
	} `json:"relays"`
}

type peerRegistryFile struct {
	Peers []struct {
		PeerID         string `json:"peer_id"`
		Enode          string `json:"enode"`
		ValidatorIndex uint64 `json:"validator_index"`
		RelayAddress   string `json:"relay_address"`
		RelayPubkey    string `json:"relay_pubkey"`
	} `json:"peers"`
}

// DefaultStore returns the process-wide TopoStake propagation metadata store.
// It stays disabled unless a local devnet relay key is provided through env.
func DefaultStore() *Store {
	defaultStoreOnce.Do(func() {
		defaultStore = NewStoreFromEnv()
	})
	return defaultStore
}

func NewStoreFromEnv() *Store {
	store := &Store{
		chainID:               getenvUint64("TOPOSTAKE_CHAIN_ID", DefaultChainID),
		maxBytes:              int(getenvUint64("TOPOSTAKE_TX_METADATA_MAX_BYTES", DefaultMaxBytes)),
		metadata:              make(map[common.Hash]TxMetadata),
		relayPubkeys:          make(map[uint64][]byte),
		relayPubkeysByAddress: make(map[string][]byte),
		validatorAddresses:    make(map[uint64]string),
		addressValidators:     make(map[string]uint64),
		peers:                 make(map[string]relayIdentity),
		addrs:                 make(map[string]relayIdentity),
		serviceIdentities:     make(map[string]relayIdentity),
		blocks:                make(map[common.Hash]*BlockEvidence),
		settlements:           make(map[string]*SettlementPayload),
		settlementsByRoot:     make(map[common.Hash]*SettlementPayload),
		settlementRootByKey:   make(map[string]common.Hash),
		executedSettlements:   make(map[string]bool),
	}
	store.epoch.Store(getenvUint64("TOPOSTAKE_RELAY_EPOCH", 0))
	store.loadRelayRegistryFromEnv()
	store.loadPeerRegistryFromEnv()
	store.loadPrivateRelayRegistryFromEnv()

	validatorRaw := strings.TrimSpace(os.Getenv("TOPOSTAKE_RELAY_VALIDATOR_INDEX"))
	privateRaw := strings.TrimSpace(os.Getenv("TOPOSTAKE_RELAY_PRIVATE_KEY"))
	if validatorRaw == "" || privateRaw == "" {
		return store
	}
	validator, err := strconv.ParseUint(validatorRaw, 10, 64)
	if err != nil {
		txMetadataInvalidMeter.Mark(1)
		return store
	}
	secret, err := secretKeyFromHex(privateRaw)
	if err != nil {
		txMetadataInvalidMeter.Mark(1)
		return store
	}
	store.enabled = true
	store.localValidator = validator
	store.localAddress = store.addressForValidator(validator)
	store.secret = secret
	store.publicKey = new(blst.P2Affine).From(secret).Compress()
	store.registerRelayIdentity(validator, store.localAddress, store.publicKey)
	return store
}

func (s *Store) Enabled() bool {
	return s != nil && s.enabled
}

func (s *Store) EnsureLocalTransactions(txs types.Transactions) {
	if !s.Enabled() {
		return
	}
	for _, tx := range txs {
		if tx == nil {
			continue
		}
		s.EnsureLocalHash(tx.Hash())
	}
}

func (s *Store) EnsureLocalHash(hash common.Hash) {
	if !s.Enabled() {
		return
	}
	s.lock.RLock()
	_, ok := s.metadata[hash]
	s.lock.RUnlock()
	if ok {
		return
	}
	meta, err := s.newOriginMetadata(hash)
	if err != nil {
		txMetadataInvalidMeter.Mark(1)
		return
	}
	s.lock.Lock()
	if _, ok := s.metadata[hash]; !ok {
		s.metadata[hash] = meta
		txMetadataCreatedMeter.Mark(1)
		txMetadataBytesMeter.Mark(int64(len(meta)))
	}
	s.lock.Unlock()
}

func (s *Store) InjectPathEvidence(hash common.Hash, validators []uint64) (TxMetadata, error) {
	if s == nil {
		return nil, fmt.Errorf("topostake store is nil")
	}
	if len(validators) < 2 {
		return nil, fmt.Errorf("topostake path requires at least origin and receiver")
	}
	secrets, err := topostakePrivateRelaySecretsFromEnv(s)
	if err != nil {
		return nil, err
	}
	seen := make(map[uint64]struct{}, len(validators))
	for _, validator := range validators {
		if _, ok := seen[validator]; ok {
			return nil, fmt.Errorf("repeated validator %d", validator)
		}
		seen[validator] = struct{}{}
		if secrets[validator] == nil {
			return nil, fmt.Errorf("missing private key for validator %d", validator)
		}
	}

	epoch := s.epoch.Load()
	origin := validators[0]
	originAddress := s.addressForValidator(origin)
	originSecret := secrets[origin]
	originPubkey := new(blst.P2Affine).From(originSecret).Compress()
	originSignature := new(blst.P1Affine).Sign(
		originSecret,
		originStatement(s.chainID, epoch, hash, originAddress),
		[]byte(Domain),
	).Compress()
	meta := propagationMetadata{
		Version:                   1,
		Domain:                    Domain,
		ChainID:                   s.chainID,
		Epoch:                     epoch,
		TxHash:                    hash.Hex(),
		OriginRelayAddress:        originAddress,
		OriginRelayValidatorIndex: origin,
		OriginRelayPubkey:         "0x" + hex.EncodeToString(originPubkey),
		OriginSignature:           "0x" + hex.EncodeToString(originSignature),
		Paths:                     []pathEdge{},
		Status:                    "devnet_injected",
		CreatedUnixMillis:         time.Now().UnixMilli(),
	}
	for i := 1; i < len(validators); i++ {
		from := validators[i-1]
		to := validators[i]
		fromAddress := s.addressForValidator(from)
		toAddress := s.addressForValidator(to)
		prefix := chainValue(hash, meta.ChainID, meta.Epoch, meta.addressSequence(), len(meta.Paths))
		senderSignature := new(blst.P1Affine).Sign(
			secrets[from],
			edgeStatement(prefix, fromAddress, toAddress),
			[]byte(Domain),
		).Compress()
		receiverSignature := new(blst.P1Affine).Sign(
			secrets[to],
			edgeStatement(prefix, fromAddress, toAddress),
			[]byte(Domain),
		).Compress()
		meta.Paths = append(meta.Paths, pathEdge{
			From:              from,
			To:                to,
			FromAddress:       fromAddress,
			ToAddress:         toAddress,
			Prefix:            "0x" + hex.EncodeToString(prefix),
			SenderSignature:   "0x" + hex.EncodeToString(senderSignature),
			ReceiverSignature: "0x" + hex.EncodeToString(receiverSignature),
		})
	}
	encoded, err := json.Marshal(meta)
	if err != nil {
		return nil, err
	}
	if len(encoded) > s.maxBytes {
		return nil, fmt.Errorf("topostake metadata too large: %d", len(encoded))
	}

	s.lock.Lock()
	s.metadata[hash] = encoded
	s.lock.Unlock()
	txMetadataBytesMeter.Mark(int64(len(encoded)))
	txPathLengthGauge.Update(int64(len(meta.Paths)))
	return TxMetadata(encoded), nil
}

func (s *Store) MetadataBatch(hashes []common.Hash) []TxMetadata {
	return s.MetadataBatchForPeer(hashes, "")
}

func (s *Store) MetadataBatchForPeer(hashes []common.Hash, peerID string) []TxMetadata {
	return s.MetadataBatchForPeerAddress(hashes, peerID, "")
}

func (s *Store) MetadataBatchForPeerAddress(hashes []common.Hash, peerID string, remoteAddr string) []TxMetadata {
	if !s.Enabled() {
		return nil
	}
	batch := make([]TxMetadata, len(hashes))
	remoteRelay, hasPeer := s.peerRelay(peerID, remoteAddr)
	s.lock.RLock()
	for i, hash := range hashes {
		if meta := s.metadata[hash]; len(meta) > 0 {
			out := append(TxMetadata(nil), meta...)
			if hasPeer {
				withEdge, err := s.withOutgoingEdge(out, remoteRelay)
				if err != nil {
					txMetadataInvalidMeter.Mark(1)
				} else {
					out = withEdge
				}
			} else if peerID != "" {
				txMetadataInvalidMeter.Mark(1)
			}
			batch[i] = out
			txMetadataForwardMeter.Mark(1)
		}
	}
	s.lock.RUnlock()
	return batch
}

func (s *Store) RecordInbound(hashes []common.Hash, batch []TxMetadata) {
	if !s.Enabled() || len(batch) == 0 {
		return
	}
	if len(hashes) != len(batch) {
		txMetadataInvalidMeter.Mark(1)
		return
	}
	s.lock.Lock()
	defer s.lock.Unlock()
	for i, meta := range batch {
		if len(meta) == 0 {
			continue
		}
		if len(meta) > s.maxBytes {
			txMetadataInvalidMeter.Mark(1)
			continue
		}
		hash := hashes[i]
		completed, err := s.completeInbound(hash, meta)
		if err != nil {
			txMetadataInvalidMeter.Mark(1)
			continue
		}
		if _, ok := s.metadata[hash]; ok {
			continue
		}
		s.metadata[hash] = completed
		txMetadataReceivedMeter.Mark(1)
		txMetadataBytesMeter.Mark(int64(len(completed)))
	}
}

func (s *Store) RecordBlockEvidence(blockHash common.Hash, blockNumber uint64, txs types.Transactions) {
	s.RecordBlockEvidenceWithReceipts(blockHash, blockNumber, txs, nil, nil, common.Address{})
}

func (s *Store) RecordBlockEvidenceWithReceipts(blockHash common.Hash, blockNumber uint64, txs types.Transactions, receipts types.Receipts, baseFee *big.Int, feeRecipient common.Address) {
	if !s.Enabled() {
		return
	}
	s.lock.Lock()
	defer s.lock.Unlock()

	evidence := s.buildBlockEvidenceLocked(blockHash, blockNumber, txs, receipts, baseFee, feeRecipient)
	s.blocks[blockHash] = evidence
	blockEvidenceMeter.Mark(1)
	blockEvidenceTxGauge.Update(int64(evidence.EvidenceCount))
}

func (s *Store) BuildBlockEvidence(blockHash common.Hash, blockNumber uint64, txs types.Transactions, receipts types.Receipts, baseFee *big.Int, feeRecipient common.Address) *BlockEvidence {
	if !s.Enabled() {
		return nil
	}
	s.lock.Lock()
	defer s.lock.Unlock()

	return cloneBlockEvidence(s.buildBlockEvidenceLocked(blockHash, blockNumber, txs, receipts, baseFee, feeRecipient))
}

func (s *Store) buildBlockEvidenceLocked(blockHash common.Hash, blockNumber uint64, txs types.Transactions, receipts types.Receipts, baseFee *big.Int, feeRecipient common.Address) *BlockEvidence {
	evidence := &BlockEvidence{
		BlockHash:          blockHash.Hex(),
		BlockNumber:        blockNumber,
		TxCount:            len(txs),
		RecordedUnixMillis: time.Now().UnixMilli(),
		Transactions:       []BlockTransactionEvidence{},
	}
	for i, tx := range txs {
		if tx == nil {
			continue
		}
		hash := tx.Hash()
		meta := s.metadata[hash]
		if len(meta) == 0 {
			continue
		}
		txEvidence := BlockTransactionEvidence{
			Index:    i,
			TxHash:   hash.Hex(),
			Metadata: append(json.RawMessage(nil), meta...),
		}
		s.attachFeeEvidence(&txEvidence, tx, receiptAt(receipts, i), baseFee, feeRecipient)
		evidence.Transactions = append(evidence.Transactions, txEvidence)
	}
	evidence.EvidenceCount = len(evidence.Transactions)
	evidence.EvidenceRoot, evidence.AggregateSignature, evidence.AggregateSignatureCount = s.blockEvidenceCommitment(blockHash, blockNumber, evidence.Transactions)
	return evidence
}

func (s *Store) blockEvidenceCommitment(blockHash common.Hash, blockNumber uint64, txs []BlockTransactionEvidence) (string, string, int) {
	records := make([]blockSignatureRecord, 0)
	for _, tx := range txs {
		var meta propagationMetadata
		if err := json.Unmarshal(tx.Metadata, &meta); err != nil {
			txMetadataInvalidMeter.Mark(1)
			continue
		}
		meta.normalizeAddresses(s)
		records = append(records, meta.signatureRecords()...)
	}
	root := blockEvidenceRoot(blockHash, blockNumber, records, txs)
	if len(records) == 0 {
		return "0x" + hex.EncodeToString(root), "", 0
	}
	signatures := make([]*blst.P1Affine, 0, len(records))
	for _, record := range records {
		sig := new(blst.P1Affine).Uncompress(record.signature)
		if sig == nil {
			txMetadataInvalidMeter.Mark(1)
			continue
		}
		signatures = append(signatures, sig)
	}
	if len(signatures) != len(records) {
		return "0x" + hex.EncodeToString(root), "", 0
	}
	aggregate := new(blst.P1Aggregate)
	if !aggregate.Aggregate(signatures, true) {
		txMetadataInvalidMeter.Mark(1)
		return "0x" + hex.EncodeToString(root), "", 0
	}
	return "0x" + hex.EncodeToString(root), "0x" + hex.EncodeToString(aggregate.ToAffine().Compress()), len(records)
}

func receiptAt(receipts types.Receipts, index int) *types.Receipt {
	if index < 0 || index >= len(receipts) {
		return nil
	}
	return receipts[index]
}

func (s *Store) attachFeeEvidence(evidence *BlockTransactionEvidence, tx *types.Transaction, receipt *types.Receipt, baseFee *big.Int, feeRecipient common.Address) {
	if evidence == nil || tx == nil || receipt == nil {
		return
	}
	effectiveTip, err := tx.EffectiveGasTip(baseFee)
	if err != nil || effectiveTip == nil || effectiveTip.Sign() < 0 {
		return
	}
	priorityFee := new(big.Int).Mul(new(big.Int).SetUint64(receipt.GasUsed), effectiveTip)
	evidence.GasUsed = receipt.GasUsed
	evidence.EffectiveGasTipWei = effectiveTip.String()
	evidence.PriorityFeeWei = priorityFee.String()
	if baseFee != nil {
		evidence.BaseFeeWei = baseFee.String()
		evidence.IrrecoverableCostWei = new(big.Int).Mul(
			new(big.Int).SetUint64(receipt.GasUsed),
			baseFee,
		).String()
	}
	if feeRecipient != (common.Address{}) {
		evidence.FeeRecipient = feeRecipient.Hex()
	}
	if FeeEscrowEnabled() {
		evidence.EscrowRecipient = FeeEscrowAddress.Hex()
	}
}

func (s *Store) BlockEvidence(hash common.Hash) (*BlockEvidence, bool) {
	if s == nil {
		return nil, false
	}
	s.lock.RLock()
	defer s.lock.RUnlock()
	evidence, ok := s.blocks[hash]
	return cloneBlockEvidence(evidence), ok
}

func (s *Store) SubmitSettlement(payload SettlementPayload) (int, error) {
	if s == nil {
		return 0, fmt.Errorf("nil topostake store")
	}
	if strings.TrimSpace(payload.Domain) == "" {
		payload.Domain = "TOPOSTAKE_FEE_SETTLEMENT_V1"
	}
	if payload.Domain != "TOPOSTAKE_FEE_SETTLEMENT_V1" {
		return 0, fmt.Errorf("invalid settlement domain %q", payload.Domain)
	}
	if len(payload.Records) == 0 {
		return 0, fmt.Errorf("empty settlement payload")
	}
	key := settlementPayloadKey(payload.FinalizedEpoch, payload.Epoch)
	records := make([]SettlementRecord, 0, len(payload.Records))
	seen := make(map[string]bool)
	for _, record := range payload.Records {
		record.Role = strings.ToLower(strings.TrimSpace(record.Role))
		if record.Role != "proposer" && record.Role != "relay" && record.Role != "burned" {
			return 0, fmt.Errorf("invalid settlement role %q", record.Role)
		}
		record.PayoutAddress = normalizeRelayAddress(record.PayoutAddress)
		if record.Role != "burned" && record.PayoutAddress == "" {
			return 0, fmt.Errorf("missing payout address for %s settlement", record.Role)
		}
		if _, ok := amountFromDecimal(record.AmountWei); !ok {
			return 0, fmt.Errorf("invalid settlement amount %q", record.AmountWei)
		}
		if record.Epoch == 0 {
			record.Epoch = payload.Epoch
		}
		if record.Epoch != payload.Epoch {
			return 0, fmt.Errorf("record epoch %d does not match payload epoch %d", record.Epoch, payload.Epoch)
		}
		if strings.TrimSpace(record.ID) == "" {
			record.ID = settlementRecordID(record)
		}
		if seen[record.ID] {
			return 0, fmt.Errorf("duplicate settlement record id %q", record.ID)
		}
		seen[record.ID] = true
		records = append(records, record)
	}
	payload.Records = records
	s.lock.Lock()
	defer s.lock.Unlock()
	if s.executedSettlements[key] {
		settlementSkippedMeter.Mark(1)
		return 0, nil
	}
	if _, exists := s.settlements[key]; !exists {
		s.settlementOrder = append(s.settlementOrder, key)
	} else if oldRoot := s.settlementRootByKey[key]; oldRoot != (common.Hash{}) {
		delete(s.settlementsByRoot, oldRoot)
	}
	clone := payload
	clone.Records = append([]SettlementRecord(nil), payload.Records...)
	root := settlementPayloadCommitment(settlementPayloadRoot(clone))
	s.settlements[key] = &clone
	s.settlementsByRoot[root] = &clone
	s.settlementRootByKey[key] = root
	for len(s.settlementOrder) > 128 {
		oldest := s.settlementOrder[0]
		s.settlementOrder = s.settlementOrder[1:]
		if !s.executedSettlements[oldest] {
			if oldRoot := s.settlementRootByKey[oldest]; oldRoot != (common.Hash{}) {
				delete(s.settlementsByRoot, oldRoot)
			}
			delete(s.settlements, oldest)
			delete(s.settlementRootByKey, oldest)
		}
	}
	settlementSubmittedMeter.Mark(1)
	return len(payload.Records), nil
}

func (s *Store) PendingSettlementRoot() common.Hash {
	if s == nil || !FeeEscrowEnabled() {
		return common.Hash{}
	}
	s.lock.RLock()
	defer s.lock.RUnlock()
	for _, key := range s.settlementOrder {
		if s.executedSettlements[key] {
			continue
		}
		if root := s.settlementRootByKey[key]; root != (common.Hash{}) {
			return root
		}
	}
	return common.Hash{}
}

func (s *Store) SettlementRecordsForRoot(root common.Hash) []types.TopoStakeSettlementRecord {
	if s == nil || root == (common.Hash{}) {
		return nil
	}
	s.lock.RLock()
	defer s.lock.RUnlock()
	payload := s.settlementsByRoot[root]
	if payload == nil {
		return nil
	}
	records := make([]types.TopoStakeSettlementRecord, 0, len(payload.Records))
	for _, record := range payload.Records {
		records = append(records, types.TopoStakeSettlementRecord{
			FinalizedEpoch: payload.FinalizedEpoch,
			Epoch:          payload.Epoch,
			Role:           record.Role,
			ValidatorIndex: record.ValidatorIndex,
			PayoutAddress:  record.PayoutAddress,
			AmountWei:      strings.TrimSpace(record.AmountWei),
			ID:             record.ID,
		})
	}
	return records
}

func (s *Store) SettlementRoot(finalizedEpoch, epoch uint64) common.Hash {
	if s == nil {
		return common.Hash{}
	}
	s.lock.RLock()
	defer s.lock.RUnlock()
	return s.settlementRootByKey[settlementPayloadKey(finalizedEpoch, epoch)]
}

func (s *Store) ApplyCommittedSettlement(root common.Hash, statedb *state.StateDB) int {
	applied, _ := s.applyCommittedSettlement(root, nil, statedb, true)
	return applied
}

func (s *Store) ApplyCommittedSettlementForBuild(root common.Hash, statedb *state.StateDB) int {
	applied, _ := s.applyCommittedSettlement(root, nil, statedb, false)
	return applied
}

func (s *Store) ApplyCommittedSettlementRecords(root common.Hash, records []types.TopoStakeSettlementRecord, statedb *state.StateDB, markExecuted bool) (int, error) {
	return s.applyCommittedSettlement(root, records, statedb, markExecuted)
}

func (s *Store) applyCommittedSettlement(root common.Hash, blockRecords []types.TopoStakeSettlementRecord, statedb *state.StateDB, markExecuted bool) (int, error) {
	if s == nil || statedb == nil || !FeeEscrowEnabled() {
		return 0, nil
	}
	if root == (common.Hash{}) {
		return 0, nil
	}
	var payload *SettlementPayload
	hasBlockRecords := len(blockRecords) > 0
	if hasBlockRecords {
		converted, err := settlementPayloadFromBlockRecords(blockRecords)
		if err != nil {
			return 0, err
		}
		computed := settlementPayloadCommitment(settlementPayloadRoot(converted))
		if computed != root {
			return 0, fmt.Errorf("topostake settlement root mismatch: committed %s computed %s", root, computed)
		}
		payload = &converted
	} else {
		if SettlementMutationEnabled() {
			return 0, fmt.Errorf("missing block-carried topostake settlement records for committed root %s", root)
		}
		s.lock.RLock()
		payload = s.settlementsByRoot[root]
		s.lock.RUnlock()
		if payload == nil {
			if markExecuted {
				settlementSkippedMeter.Mark(1)
			}
			return 0, nil
		}
	}
	key := settlementPayloadKey(payload.FinalizedEpoch, payload.Epoch)
	s.lock.Lock()
	defer s.lock.Unlock()
	if markExecuted && !hasBlockRecords && s.executedSettlements[key] {
		return 0, nil
	}
	if !SettlementMutationEnabled() {
		if markExecuted {
			s.executedSettlements[key] = true
			settlementSkippedMeter.Mark(1)
		}
		return 0, nil
	}
	total := new(uint256.Int)
	amounts := make([]uint256.Int, len(payload.Records))
	ok := true
	for i, record := range payload.Records {
		amount, valid := amountFromDecimal(record.AmountWei)
		if !valid {
			ok = false
			break
		}
		amounts[i] = *amount
		total.Add(total, amount)
	}
	if !ok {
		return 0, fmt.Errorf("invalid topostake settlement amount for root %s", root)
	}
	if total.IsZero() {
		return 0, fmt.Errorf("zero topostake settlement total for root %s", root)
	}
	if statedb.GetBalance(FeeEscrowAddress).Cmp(total) < 0 {
		return 0, fmt.Errorf("insufficient topostake escrow balance for root %s: have %s need %s", root, statedb.GetBalance(FeeEscrowAddress), total)
	}
	statedb.SubBalance(FeeEscrowAddress, total, tracing.BalanceDecreaseGasBuy)
	for i, record := range payload.Records {
		if record.Role == "burned" {
			continue
		}
		statedb.AddBalance(common.HexToAddress(record.PayoutAddress), &amounts[i], tracing.BalanceIncreaseRewardTransactionFee)
	}
	if markExecuted {
		s.executedSettlements[key] = true
		settlementAppliedMeter.Mark(1)
	}
	return 1, nil
}

func SettlementRootFromExtra(extra []byte) common.Hash {
	if len(extra) != common.HashLength {
		return common.Hash{}
	}
	if !bytes.Equal(extra[:len(topostakeSettlementExtraPrefix)], topostakeSettlementExtraPrefix) {
		return common.Hash{}
	}
	return common.BytesToHash(extra)
}

func SettlementExtraFromRoot(root common.Hash) []byte {
	if root == (common.Hash{}) {
		return nil
	}
	return root.Bytes()
}

func settlementPayloadFromBlockRecords(records []types.TopoStakeSettlementRecord) (SettlementPayload, error) {
	if len(records) == 0 {
		return SettlementPayload{}, fmt.Errorf("empty topostake settlement records")
	}
	payload := SettlementPayload{
		Domain:         "TOPOSTAKE_FEE_SETTLEMENT_V1",
		FinalizedEpoch: records[0].FinalizedEpoch,
		Epoch:          records[0].Epoch,
		Records:        make([]SettlementRecord, 0, len(records)),
	}
	for _, record := range records {
		if record.FinalizedEpoch != payload.FinalizedEpoch || record.Epoch != payload.Epoch {
			return SettlementPayload{}, fmt.Errorf("mixed topostake settlement epochs in block records")
		}
		settlement := SettlementRecord{
			ID:             strings.TrimSpace(record.ID),
			Epoch:          record.Epoch,
			Role:           strings.ToLower(strings.TrimSpace(record.Role)),
			ValidatorIndex: record.ValidatorIndex,
			PayoutAddress:  normalizeRelayAddress(record.PayoutAddress),
			AmountWei:      strings.TrimSpace(record.AmountWei),
		}
		if settlement.ID == "" {
			settlement.ID = settlementRecordID(settlement)
		}
		payload.Records = append(payload.Records, settlement)
	}
	return payload, nil
}

func settlementPayloadKey(finalizedEpoch, epoch uint64) string {
	// The settlement pays rewards for an evidence epoch. Multiple CL nodes can
	// first observe and submit that same evidence epoch at different finalized
	// epochs, so finalizedEpoch must not create another pending payout.
	return fmt.Sprintf("%d", epoch)
}

func settlementRecordID(record SettlementRecord) string {
	return fmt.Sprintf("%d:%s:%d:%s:%s", record.Epoch, record.Role, record.ValidatorIndex, normalizeRelayAddress(record.PayoutAddress), strings.TrimSpace(record.AmountWei))
}

func settlementPayloadRoot(payload SettlementPayload) common.Hash {
	hasher := sha256.New()
	hasher.Write([]byte("TOPOSTAKE_FEE_SETTLEMENT_ROOT_V1"))
	hasher.Write([]byte{0})
	hasher.Write([]byte(payload.Domain))
	var buf [8]byte
	binary.BigEndian.PutUint64(buf[:], payload.FinalizedEpoch)
	hasher.Write(buf[:])
	binary.BigEndian.PutUint64(buf[:], payload.Epoch)
	hasher.Write(buf[:])
	records := append([]SettlementRecord(nil), payload.Records...)
	sort.Slice(records, func(i, j int) bool {
		return records[i].ID < records[j].ID
	})
	for _, record := range records {
		hasher.Write([]byte{0})
		hasher.Write([]byte(record.ID))
		hasher.Write([]byte{0})
		hasher.Write([]byte(record.Role))
		binary.BigEndian.PutUint64(buf[:], record.ValidatorIndex)
		hasher.Write(buf[:])
		hasher.Write([]byte{0})
		hasher.Write([]byte(normalizeRelayAddress(record.PayoutAddress)))
		hasher.Write([]byte{0})
		hasher.Write([]byte(strings.TrimSpace(record.AmountWei)))
	}
	return common.BytesToHash(hasher.Sum(nil))
}

var topostakeSettlementExtraPrefix = []byte{'T', 'S', 'S', '1'}

func settlementPayloadCommitment(root common.Hash) common.Hash {
	var out [common.HashLength]byte
	copy(out[:], topostakeSettlementExtraPrefix)
	copy(out[len(topostakeSettlementExtraPrefix):], root[:common.HashLength-len(topostakeSettlementExtraPrefix)])
	return common.BytesToHash(out[:])
}

func amountFromDecimal(input string) (*uint256.Int, bool) {
	input = strings.TrimSpace(input)
	if input == "" {
		return nil, false
	}
	value, ok := new(big.Int).SetString(input, 10)
	if !ok || value.Sign() < 0 || value.BitLen() > 256 {
		return nil, false
	}
	out, overflow := uint256.FromBig(value)
	if overflow {
		return nil, false
	}
	return out, true
}

func normalizeEvidenceRoot(root string) string {
	root = strings.TrimSpace(strings.ToLower(root))
	if root == "" {
		return ""
	}
	if strings.HasPrefix(root, "0x") {
		return root
	}
	return "0x" + root
}

func (s *Store) newOriginMetadata(hash common.Hash) (TxMetadata, error) {
	epoch := s.epoch.Load()
	localAddress := s.localRelayAddress()
	statement := originStatement(s.chainID, epoch, hash, localAddress)
	signature := new(blst.P1Affine).Sign(s.secret, statement, []byte(Domain)).Compress()
	meta := propagationMetadata{
		Version:                   1,
		Domain:                    Domain,
		ChainID:                   s.chainID,
		Epoch:                     epoch,
		TxHash:                    hash.Hex(),
		OriginRelayAddress:        localAddress,
		OriginRelayValidatorIndex: s.localValidator,
		OriginRelayPubkey:         "0x" + hex.EncodeToString(s.publicKey),
		OriginSignature:           "0x" + hex.EncodeToString(signature),
		Paths:                     []pathEdge{},
		Status:                    "origin",
		CreatedUnixMillis:         time.Now().UnixMilli(),
	}
	encoded, err := json.Marshal(meta)
	if err != nil {
		return nil, err
	}
	if len(encoded) > s.maxBytes {
		return nil, fmt.Errorf("topostake metadata too large: %d", len(encoded))
	}
	txMetadataSignedOrigin.Mark(1)
	txPathLengthGauge.Update(0)
	return TxMetadata(encoded), nil
}

func (s *Store) withOutgoingEdge(raw TxMetadata, remote relayIdentity) (TxMetadata, error) {
	var meta propagationMetadata
	if err := json.Unmarshal(raw, &meta); err != nil {
		return nil, err
	}
	meta.normalizeAddresses(s)
	if meta.ChainID != s.chainID {
		return nil, fmt.Errorf("chain id mismatch")
	}
	if meta.TxHash == "" {
		return nil, fmt.Errorf("missing tx hash")
	}
	if meta.hasPendingHop() {
		return raw, nil
	}
	remote.Address = normalizeRelayAddress(remote.Address)
	if remote.Address == "" {
		remote.Address = s.addressForValidator(remote.ValidatorIndex)
	}
	if meta.hasAddress(remote.Address) {
		return nil, fmt.Errorf("repeated relay address %s", remote.Address)
	}
	fromIndex, fromAddress := meta.currentTail()
	if fromAddress != s.localRelayAddress() {
		return nil, fmt.Errorf("local relay address %s is not metadata tail %s", s.localRelayAddress(), fromAddress)
	}
	txHash := common.HexToHash(meta.TxHash)
	prefix := chainValue(txHash, meta.ChainID, meta.Epoch, meta.addressSequence(), len(meta.Paths))
	statement := edgeStatement(prefix, fromAddress, remote.Address)
	signature := new(blst.P1Affine).Sign(s.secret, statement, []byte(Domain)).Compress()
	meta.Paths = append(meta.Paths, pathEdge{
		From:            fromIndex,
		To:              remote.ValidatorIndex,
		FromAddress:     fromAddress,
		ToAddress:       remote.Address,
		Prefix:          "0x" + hex.EncodeToString(prefix),
		SenderSignature: "0x" + hex.EncodeToString(signature),
	})
	meta.Status = "pending_edge"
	encoded, err := json.Marshal(meta)
	if err != nil {
		return nil, err
	}
	if len(encoded) > s.maxBytes {
		return nil, fmt.Errorf("topostake metadata too large: %d", len(encoded))
	}
	txMetadataSignedSender.Mark(1)
	txPathLengthGauge.Update(int64(len(meta.Paths)))
	return TxMetadata(encoded), nil
}

func (s *Store) completeInbound(hash common.Hash, raw TxMetadata) (TxMetadata, error) {
	var meta propagationMetadata
	if err := json.Unmarshal(raw, &meta); err != nil {
		return nil, err
	}
	meta.normalizeAddresses(s)
	if meta.Domain != Domain {
		return nil, fmt.Errorf("domain mismatch")
	}
	if meta.ChainID != s.chainID {
		return nil, fmt.Errorf("chain id mismatch")
	}
	if meta.TxHash != hash.Hex() {
		return nil, fmt.Errorf("tx hash mismatch")
	}
	if !s.verifyOrigin(meta) {
		return nil, fmt.Errorf("invalid origin signature")
	}
	if len(meta.Paths) == 0 {
		return nil, fmt.Errorf("missing pending edge")
	}
	if meta.hasRepeatedValidators() {
		return nil, fmt.Errorf("repeated relay identity")
	}
	last := &meta.Paths[len(meta.Paths)-1]
	if normalizeRelayAddress(last.ToAddress) != s.localRelayAddress() {
		return nil, fmt.Errorf("pending edge targets relay address %s, local relay address %s", last.ToAddress, s.localRelayAddress())
	}
	if last.ReceiverSignature != "" {
		return nil, fmt.Errorf("edge already has receiver signature")
	}
	if !s.verifySender(meta, len(meta.Paths)-1) {
		txMetadataVerifiedFail.Mark(1)
		return nil, fmt.Errorf("invalid sender signature")
	}
	txMetadataVerifiedOK.Mark(1)
	prefix, err := hexBytes(last.Prefix)
	if err != nil {
		return nil, err
	}
	statement := edgeStatement(prefix, last.FromAddress, last.ToAddress)
	signature := new(blst.P1Affine).Sign(s.secret, statement, []byte(Domain)).Compress()
	last.ReceiverSignature = "0x" + hex.EncodeToString(signature)
	meta.Status = "edge_received"
	encoded, err := json.Marshal(meta)
	if err != nil {
		return nil, err
	}
	if len(encoded) > s.maxBytes {
		return nil, fmt.Errorf("topostake metadata too large: %d", len(encoded))
	}
	txMetadataSignedRecv.Mark(1)
	txPathLengthGauge.Update(int64(len(meta.Paths)))
	return TxMetadata(encoded), nil
}

func (s *Store) verifyOrigin(meta propagationMetadata) bool {
	meta.normalizeAddresses(s)
	pubkey := s.pubkey(meta.OriginRelayAddress)
	if len(pubkey) == 0 {
		pubkey, _ = hexBytes(meta.OriginRelayPubkey)
	}
	if len(pubkey) == 0 {
		return false
	}
	sigBytes, err := hexBytes(meta.OriginSignature)
	if err != nil {
		return false
	}
	pub := new(blst.P2Affine).Uncompress(pubkey)
	sig := new(blst.P1Affine).Uncompress(sigBytes)
	if pub == nil || sig == nil {
		return false
	}
	txHash := common.HexToHash(meta.TxHash)
	return sig.Verify(true, pub, false, originStatement(meta.ChainID, meta.Epoch, txHash, meta.OriginRelayAddress), []byte(Domain))
}

func (s *Store) verifySender(meta propagationMetadata, idx int) bool {
	if idx < 0 || idx >= len(meta.Paths) {
		return false
	}
	edge := meta.Paths[idx]
	meta.normalizeAddresses(s)
	expectedPrefix := chainValue(common.HexToHash(meta.TxHash), meta.ChainID, meta.Epoch, meta.addressSequence(), idx)
	if edge.Prefix != "0x"+hex.EncodeToString(expectedPrefix) {
		return false
	}
	pubkey := s.pubkey(edge.FromAddress)
	if len(pubkey) == 0 {
		return false
	}
	sigBytes, err := hexBytes(edge.SenderSignature)
	if err != nil {
		return false
	}
	pub := new(blst.P2Affine).Uncompress(pubkey)
	sig := new(blst.P1Affine).Uncompress(sigBytes)
	if pub == nil || sig == nil {
		return false
	}
	return sig.Verify(true, pub, false, edgeStatement(expectedPrefix, edge.FromAddress, edge.ToAddress), []byte(Domain))
}

func (s *Store) peerRelay(peerID string, remoteAddr string) (relayIdentity, bool) {
	peerID = normalizePeerID(peerID)
	host := normalizeAddr(remoteAddr)

	s.lock.Lock()
	defer s.lock.Unlock()
	if peerID == "" {
		if host == "" {
			return relayIdentity{}, false
		}
	} else if validator, ok := s.peers[peerID]; ok {
		return validator, true
	}
	if host == "" {
		return relayIdentity{}, false
	}
	if validator, ok := s.addrs[host]; ok {
		return validator, true
	}
	s.refreshServiceAddresses()
	validator, ok := s.addrs[host]
	return validator, ok
}

func (s *Store) peerValidator(peerID string, remoteAddr string) (uint64, bool) {
	relay, ok := s.peerRelay(peerID, remoteAddr)
	return relay.ValidatorIndex, ok
}

func (s *Store) pubkey(address string) []byte {
	address = normalizeRelayAddress(address)
	pubkey := s.relayPubkeysByAddress[address]
	if len(pubkey) == 0 {
		if validator, ok := s.addressValidators[address]; ok {
			pubkey = s.relayPubkeys[validator]
		}
	}
	if len(pubkey) == 0 {
		for validator, candidate := range s.relayPubkeys {
			if s.addressForValidator(validator) == address {
				pubkey = candidate
				break
			}
		}
	}
	if len(pubkey) == 0 {
		return nil
	}
	return append([]byte(nil), pubkey...)
}

func (s *Store) loadRelayRegistryFromEnv() {
	raw := strings.TrimSpace(os.Getenv("TOPOSTAKE_RELAY_PUBLIC_REGISTRY_JSON"))
	if raw == "" {
		raw = readOptionalFile(os.Getenv("TOPOSTAKE_RELAY_PUBLIC_REGISTRY"))
	}
	if raw == "" {
		return
	}
	var registry relayRegistryFile
	if err := json.Unmarshal([]byte(raw), &registry); err != nil {
		txMetadataInvalidMeter.Mark(1)
		return
	}
	for _, relay := range registry.Relays {
		pubkey, err := hexBytes(relay.RelayPubkey)
		if err != nil {
			txMetadataInvalidMeter.Mark(1)
			continue
		}
		address := relay.RelayAddress
		if address == "" {
			address = relay.PayoutAddress
		}
		s.registerRelayIdentity(relay.ValidatorIndex, address, pubkey)
		s.registerServiceAddress(relay.ServiceName, relayIdentity{
			ValidatorIndex: relay.ValidatorIndex,
			Address:        s.addressForValidator(relay.ValidatorIndex),
		})
	}
}

func (s *Store) loadPeerRegistryFromEnv() {
	raw := strings.TrimSpace(os.Getenv("TOPOSTAKE_RELAY_PEER_REGISTRY_JSON"))
	if raw == "" {
		raw = readOptionalFile(os.Getenv("TOPOSTAKE_RELAY_PEER_REGISTRY"))
	}
	if raw == "" {
		return
	}
	var registry peerRegistryFile
	if err := json.Unmarshal([]byte(raw), &registry); err != nil {
		txMetadataInvalidMeter.Mark(1)
		return
	}
	for _, peer := range registry.Peers {
		identity := relayIdentity{
			ValidatorIndex: peer.ValidatorIndex,
			Address:        s.resolveRelayAddress(peer.ValidatorIndex, peer.RelayAddress),
		}
		if peer.PeerID != "" {
			s.peers[normalizePeerID(peer.PeerID)] = identity
		}
		if peer.Enode != "" {
			s.peers[normalizePeerID(peer.Enode)] = identity
		}
		if peer.RelayPubkey != "" {
			pubkey, err := hexBytes(peer.RelayPubkey)
			if err != nil {
				txMetadataInvalidMeter.Mark(1)
				continue
			}
			s.registerRelayIdentity(peer.ValidatorIndex, identity.Address, pubkey)
		}
	}
}

func (s *Store) loadPrivateRelayRegistryFromEnv() {
	raw := strings.TrimSpace(os.Getenv("TOPOSTAKE_RELAY_PRIVATE_REGISTRY_JSON"))
	if raw == "" {
		raw = readOptionalFile(os.Getenv("TOPOSTAKE_RELAY_PRIVATE_REGISTRY"))
	}
	if raw == "" {
		return
	}
	var registry privateRelayRegistryFile
	if err := json.Unmarshal([]byte(raw), &registry); err != nil {
		txMetadataInvalidMeter.Mark(1)
		return
	}
	explicitNodeIndex, hasExplicitNodeIndex := getenvOptionalUint64("TOPOSTAKE_RELAY_NODE_INDEX")
	localAddrs := localIPSet()
	for _, relay := range registry.Relays {
		pubkey, err := hexBytes(relay.RelayPubkey)
		if err != nil {
			txMetadataInvalidMeter.Mark(1)
			continue
		}
		address := relay.RelayAddress
		if address == "" {
			address = relay.PayoutAddress
		}
		s.registerRelayIdentity(relay.ValidatorIndex, address, pubkey)
		identity := relayIdentity{
			ValidatorIndex: relay.ValidatorIndex,
			Address:        s.addressForValidator(relay.ValidatorIndex),
		}
		resolved := make([]string, 0)
		for _, serviceName := range serviceNamesForRelay(relay.ServiceName, relay.NodeIndex) {
			resolved = append(resolved, s.registerServiceAddress(serviceName, identity)...)
		}
		isLocal := hasExplicitNodeIndex && explicitNodeIndex == relay.NodeIndex
		if !isLocal {
			isLocal = hasLocalAddress(localAddrs, resolved)
		}
		if s.enabled || !isLocal {
			continue
		}
		secret, err := secretKeyFromHex(relay.RelayPrivateKey)
		if err != nil {
			txMetadataInvalidMeter.Mark(1)
			continue
		}
		s.enabled = true
		s.localValidator = relay.ValidatorIndex
		s.localAddress = identity.Address
		s.secret = secret
		s.publicKey = new(blst.P2Affine).From(secret).Compress()
		s.registerRelayIdentity(relay.ValidatorIndex, s.localAddress, s.publicKey)
	}
}

func (s *Store) registerServiceAddress(serviceName string, identity relayIdentity) []string {
	serviceName = strings.TrimSpace(serviceName)
	if serviceName == "" {
		return nil
	}
	s.serviceIdentities[serviceName] = identity
	hosts, err := lookupServiceHosts(serviceName)
	if err != nil {
		return nil
	}
	for _, host := range hosts {
		normalized := normalizeAddr(host)
		if normalized != "" {
			s.addrs[normalized] = identity
		}
	}
	return hosts
}

func topostakePrivateRelaySecretsFromEnv(s *Store) (map[uint64]*blst.SecretKey, error) {
	raw := strings.TrimSpace(os.Getenv("TOPOSTAKE_RELAY_PRIVATE_REGISTRY_JSON"))
	if raw == "" {
		raw = readOptionalFile(os.Getenv("TOPOSTAKE_RELAY_PRIVATE_REGISTRY"))
	}
	if raw == "" {
		return nil, fmt.Errorf("missing TOPOSTAKE_RELAY_PRIVATE_REGISTRY_JSON")
	}
	var registry privateRelayRegistryFile
	if err := json.Unmarshal([]byte(raw), &registry); err != nil {
		return nil, err
	}
	secrets := make(map[uint64]*blst.SecretKey, len(registry.Relays))
	for _, relay := range registry.Relays {
		pubkey, err := hexBytes(relay.RelayPubkey)
		if err != nil {
			return nil, err
		}
		address := relay.RelayAddress
		if address == "" {
			address = relay.PayoutAddress
		}
		s.registerRelayIdentity(relay.ValidatorIndex, address, pubkey)
		secret, err := secretKeyFromHex(relay.RelayPrivateKey)
		if err != nil {
			return nil, err
		}
		secrets[relay.ValidatorIndex] = secret
	}
	return secrets, nil
}

func (s *Store) refreshServiceAddresses() {
	for serviceName, identity := range s.serviceIdentities {
		hosts, err := lookupServiceHosts(serviceName)
		if err != nil {
			continue
		}
		for _, host := range hosts {
			normalized := normalizeAddr(host)
			if normalized != "" {
				s.addrs[normalized] = identity
			}
		}
	}
}

func lookupServiceHosts(serviceName string) ([]string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), serviceLookupTimeout)
	defer cancel()
	return net.DefaultResolver.LookupHost(ctx, serviceName)
}

func (m propagationMetadata) indexSequence() []uint64 {
	nodes := []uint64{m.OriginRelayValidatorIndex}
	for _, edge := range m.Paths {
		nodes = append(nodes, edge.To)
	}
	return nodes
}

func (m propagationMetadata) addressSequence() []string {
	nodes := []string{normalizeRelayAddress(m.OriginRelayAddress)}
	for _, edge := range m.Paths {
		nodes = append(nodes, normalizeRelayAddress(edge.ToAddress))
	}
	return nodes
}

func (m propagationMetadata) currentTail() (uint64, string) {
	if len(m.Paths) == 0 {
		return m.OriginRelayValidatorIndex, normalizeRelayAddress(m.OriginRelayAddress)
	}
	edge := m.Paths[len(m.Paths)-1]
	return edge.To, normalizeRelayAddress(edge.ToAddress)
}

func (m propagationMetadata) hasPendingHop() bool {
	return len(m.Paths) > 0 && m.Paths[len(m.Paths)-1].ReceiverSignature == ""
}

func (m propagationMetadata) hasAddress(address string) bool {
	address = normalizeRelayAddress(address)
	for _, node := range m.addressSequence() {
		if node == address {
			return true
		}
	}
	return false
}

func (m propagationMetadata) hasRepeatedValidators() bool {
	seen := make(map[string]struct{})
	addresses := m.addressSequence()
	for _, node := range addresses {
		if _, ok := seen[node]; ok {
			return true
		}
		seen[node] = struct{}{}
	}
	indexes := m.indexSequence()
	for i, edge := range m.Paths {
		if i >= len(indexes)-1 || edge.From != indexes[i] || edge.To != indexes[i+1] {
			return true
		}
		if i >= len(addresses)-1 ||
			normalizeRelayAddress(edge.FromAddress) != addresses[i] ||
			normalizeRelayAddress(edge.ToAddress) != addresses[i+1] {
			return true
		}
	}
	return false
}

func (m propagationMetadata) signatureRecords() []blockSignatureRecord {
	txHash := common.HexToHash(m.TxHash)
	records := make([]blockSignatureRecord, 0, 1+2*len(m.Paths))
	if sig, err := hexBytes(m.OriginSignature); err == nil {
		records = append(records, blockSignatureRecord{
			signer:    normalizeRelayAddress(m.OriginRelayAddress),
			statement: originStatement(m.ChainID, m.Epoch, txHash, m.OriginRelayAddress),
			signature: sig,
		})
	}
	nodes := m.addressSequence()
	for i, edge := range m.Paths {
		prefix := chainValue(txHash, m.ChainID, m.Epoch, nodes, i)
		statement := edgeStatement(prefix, edge.FromAddress, edge.ToAddress)
		if sig, err := hexBytes(edge.SenderSignature); err == nil {
			records = append(records, blockSignatureRecord{
				signer:    normalizeRelayAddress(edge.FromAddress),
				statement: statement,
				signature: sig,
			})
		}
		if sig, err := hexBytes(edge.ReceiverSignature); err == nil {
			records = append(records, blockSignatureRecord{
				signer:    normalizeRelayAddress(edge.ToAddress),
				statement: statement,
				signature: sig,
			})
		}
	}
	return records
}

func blockEvidenceRoot(blockHash common.Hash, blockNumber uint64, records []blockSignatureRecord, txs []BlockTransactionEvidence) []byte {
	var buf [8]byte
	digest := sha256.New()
	digest.Write([]byte("TOPOSTAKE_BLOCK_EVIDENCE_V1"))
	digest.Write(blockHash.Bytes())
	binary.BigEndian.PutUint64(buf[:], blockNumber)
	digest.Write(buf[:])
	binary.BigEndian.PutUint64(buf[:], uint64(len(txs)))
	digest.Write(buf[:])
	for _, tx := range txs {
		binary.BigEndian.PutUint64(buf[:], uint64(tx.Index))
		digest.Write(buf[:])
		digest.Write(common.HexToHash(tx.TxHash).Bytes())
		binary.BigEndian.PutUint64(buf[:], tx.GasUsed)
		digest.Write(buf[:])
		writeEvidenceString(digest, tx.EffectiveGasTipWei)
		writeEvidenceString(digest, tx.PriorityFeeWei)
		writeEvidenceString(digest, tx.BaseFeeWei)
		writeEvidenceString(digest, tx.IrrecoverableCostWei)
		writeEvidenceString(digest, normalizeRelayAddress(tx.FeeRecipient))
		writeEvidenceString(digest, normalizeRelayAddress(tx.EscrowRecipient))
	}
	binary.BigEndian.PutUint64(buf[:], uint64(len(records)))
	digest.Write(buf[:])
	for _, record := range records {
		digest.Write(hashIdentity(record.signer))
		digest.Write(record.statement)
		digest.Write(record.signature)
	}
	return digest.Sum(nil)
}

func writeEvidenceString(digest interface{ Write([]byte) (int, error) }, value string) {
	var buf [8]byte
	binary.BigEndian.PutUint64(buf[:], uint64(len(value)))
	digest.Write(buf[:])
	digest.Write([]byte(value))
}

func originStatement(chainID, epoch uint64, hash common.Hash, address string) []byte {
	var buf [8]byte
	digest := sha256.New()
	digest.Write([]byte(Domain))
	binary.BigEndian.PutUint64(buf[:], chainID)
	digest.Write(buf[:])
	binary.BigEndian.PutUint64(buf[:], epoch)
	digest.Write(buf[:])
	digest.Write(hash.Bytes())
	digest.Write(hashIdentity(address))
	return digest.Sum(nil)
}

func chainValue(txHash common.Hash, chainID, epoch uint64, nodes []string, nodeIdx int) []byte {
	digest := sha256.New()
	var buf [8]byte
	digest.Write([]byte(Domain))
	binary.BigEndian.PutUint64(buf[:], chainID)
	digest.Write(buf[:])
	digest.Write(txHash.Bytes())
	binary.BigEndian.PutUint64(buf[:], epoch)
	digest.Write(buf[:])
	if len(nodes) == 0 {
		return digest.Sum(nil)
	}
	digest.Write(hashIdentity(nodes[0]))
	chain := digest.Sum(nil)
	capped := nodeIdx
	if capped > len(nodes)-1 {
		capped = len(nodes) - 1
	}
	for _, node := range nodes[1 : capped+1] {
		hopDigest := sha256.New()
		hopDigest.Write(chain)
		hopDigest.Write(hashIdentity(node))
		chain = hopDigest.Sum(nil)
	}
	return chain
}

func edgeStatement(prefix []byte, from, to string) []byte {
	digest := sha256.New()
	digest.Write([]byte(Domain))
	digest.Write(prefix)
	digest.Write(hashIdentity(from))
	digest.Write(hashIdentity(to))
	return digest.Sum(nil)
}

func hashIdentity(identity string) []byte {
	digest := sha256.Sum256([]byte(normalizeRelayAddress(identity)))
	return digest[:]
}

func (s *Store) localRelayAddress() string {
	if s.localAddress == "" {
		s.localAddress = s.addressForValidator(s.localValidator)
	}
	return s.localAddress
}

func (s *Store) addressForValidator(validator uint64) string {
	if address := normalizeRelayAddress(s.validatorAddresses[validator]); address != "" {
		return address
	}
	return fallbackRelayAddress(validator)
}

func (s *Store) resolveRelayAddress(validator uint64, address string) string {
	address = normalizeRelayAddress(address)
	if address == "" {
		return s.addressForValidator(validator)
	}
	return address
}

func (s *Store) registerRelayIdentity(validator uint64, address string, pubkey []byte) string {
	address = s.resolveRelayAddress(validator, address)
	s.validatorAddresses[validator] = address
	s.addressValidators[address] = validator
	if len(pubkey) > 0 {
		copied := append([]byte(nil), pubkey...)
		s.relayPubkeys[validator] = copied
		s.relayPubkeysByAddress[address] = copied
	}
	return address
}

func (m *propagationMetadata) normalizeAddresses(s *Store) {
	m.OriginRelayAddress = s.resolveRelayAddress(m.OriginRelayValidatorIndex, m.OriginRelayAddress)
	fromIndex := m.OriginRelayValidatorIndex
	fromAddress := m.OriginRelayAddress
	for i := range m.Paths {
		edge := &m.Paths[i]
		if edge.FromAddress == "" {
			edge.FromAddress = fromAddress
		} else {
			edge.FromAddress = s.resolveRelayAddress(edge.From, edge.FromAddress)
		}
		if edge.ToAddress == "" {
			edge.ToAddress = s.addressForValidator(edge.To)
		} else {
			edge.ToAddress = s.resolveRelayAddress(edge.To, edge.ToAddress)
		}
		if edge.From == 0 && fromIndex != 0 {
			edge.From = fromIndex
		}
		fromIndex = edge.To
		fromAddress = edge.ToAddress
	}
}

func fallbackRelayAddress(validator uint64) string {
	return common.BigToAddress(new(big.Int).SetUint64(validator + 1)).Hex()
}

func normalizeRelayAddress(address string) string {
	address = strings.TrimSpace(address)
	if address == "" {
		return ""
	}
	if common.IsHexAddress(address) {
		return strings.ToLower(common.HexToAddress(address).Hex())
	}
	address = strings.TrimPrefix(strings.ToLower(address), "0x")
	if len(address) == 40 {
		if _, err := hex.DecodeString(address); err == nil {
			return strings.ToLower(common.HexToAddress("0x" + address).Hex())
		}
	}
	return strings.ToLower(address)
}

func hexBytes(input string) ([]byte, error) {
	input = strings.TrimPrefix(strings.TrimSpace(input), "0x")
	if input == "" {
		return nil, fmt.Errorf("empty hex")
	}
	return hex.DecodeString(input)
}

func normalizePeerID(peerID string) string {
	peerID = strings.TrimSpace(peerID)
	peerID = strings.TrimPrefix(peerID, "enode://")
	if at := strings.Index(peerID, "@"); at >= 0 {
		peerID = peerID[:at]
	}
	return strings.ToLower(peerID)
}

func normalizeAddr(addr string) string {
	addr = strings.TrimSpace(addr)
	if addr == "" {
		return ""
	}
	if host, _, err := net.SplitHostPort(addr); err == nil {
		addr = host
	}
	addr = strings.Trim(addr, "[]")
	if ip := net.ParseIP(addr); ip != nil {
		return ip.String()
	}
	return strings.ToLower(addr)
}

func serviceNameForNodeIndex(index uint64) string {
	return fmt.Sprintf("el-%d-geth-lighthouse", index+1)
}

func paddedServiceNameForNodeIndex(index uint64) string {
	return fmt.Sprintf("el-%02d-geth-lighthouse", index+1)
}

func serviceNamesForRelay(serviceName string, index uint64) []string {
	seen := make(map[string]struct{})
	names := make([]string, 0, 3)
	add := func(name string) {
		name = strings.TrimSpace(name)
		if name == "" {
			return
		}
		if _, ok := seen[name]; ok {
			return
		}
		seen[name] = struct{}{}
		names = append(names, name)
	}
	add(serviceName)
	add(serviceNameForNodeIndex(index))
	add(paddedServiceNameForNodeIndex(index))
	return names
}

func localIPSet() map[string]struct{} {
	out := make(map[string]struct{})
	addrs, err := net.InterfaceAddrs()
	if err != nil {
		return out
	}
	for _, addr := range addrs {
		var ip net.IP
		switch v := addr.(type) {
		case *net.IPNet:
			ip = v.IP
		case *net.IPAddr:
			ip = v.IP
		}
		if ip == nil || ip.IsLoopback() {
			continue
		}
		out[ip.String()] = struct{}{}
	}
	return out
}

func hasLocalAddress(local map[string]struct{}, candidates []string) bool {
	for _, candidate := range candidates {
		if _, ok := local[normalizeAddr(candidate)]; ok {
			return true
		}
	}
	return false
}

func readOptionalFile(path string) string {
	path = strings.TrimSpace(path)
	if path == "" {
		return ""
	}
	data, err := os.ReadFile(path)
	if err != nil {
		txMetadataInvalidMeter.Mark(1)
		return ""
	}
	return string(data)
}

func cloneBlockEvidence(evidence *BlockEvidence) *BlockEvidence {
	if evidence == nil {
		return nil
	}
	clone := *evidence
	clone.Transactions = make([]BlockTransactionEvidence, len(evidence.Transactions))
	for i, tx := range evidence.Transactions {
		clone.Transactions[i] = tx
		clone.Transactions[i].Metadata = append(json.RawMessage(nil), tx.Metadata...)
	}
	return &clone
}

func secretKeyFromHex(input string) (*blst.SecretKey, error) {
	input = strings.TrimPrefix(strings.TrimSpace(input), "0x")
	raw, err := hex.DecodeString(input)
	if err != nil {
		return nil, err
	}
	secret := new(blst.SecretKey).Deserialize(raw)
	if secret == nil {
		return nil, fmt.Errorf("invalid bls secret key")
	}
	return secret, nil
}

func getenvUint64(key string, fallback uint64) uint64 {
	raw := strings.TrimSpace(os.Getenv(key))
	if raw == "" {
		return fallback
	}
	value, err := strconv.ParseUint(raw, 10, 64)
	if err != nil {
		return fallback
	}
	return value
}

func getenvOptionalUint64(key string) (uint64, bool) {
	raw := strings.TrimSpace(os.Getenv(key))
	if raw == "" {
		return 0, false
	}
	value, err := strconv.ParseUint(raw, 10, 64)
	if err != nil {
		return 0, false
	}
	return value, true
}
