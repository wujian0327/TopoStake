use crate::blockchain::block::Block;
use crate::blockchain::path::TransactionPaths;
use crate::consensus::{RandaoSeed, Validator};
use crate::network::world_state::SlotManager;
use std::sync::Arc;

pub enum Message {
    SendBlock {
        block: Arc<Block>,
        from: String,
    },
    SendTransactionPaths {
        transaction_paths: Arc<TransactionPaths>,
        from: String,
    },
    GenerateBlock,
    GenerateTransactionPaths {
        to: String,
    },
    SendRandaoSeed,
    ReceiveRandaoSeed(RandaoSeed),
    BecomeValidator(std::collections::HashMap<String, f64>),
    ReceiveBecomeValidator(Validator),
    UpdateSlot(SlotManager),
    PrintBlockchain,
    RequestBlockSync {
        last_block_index: u64,
        from: String,
    },
    ResponseBlockSync {
        blocks: Vec<Block>,
        from: String,
    },
    UpdateValidatorStake {
        address: String,
        new_stake: f64,
    },
    UpdateNodeBalance(f64),
    BlockProductionFailed {
        node_index: u32,
        slot: u64,
        reason: String,
    },
}

impl Message {
    pub fn new_block_msg(block: Arc<Block>, from: String) -> Message {
        Message::SendBlock { block, from }
    }

    pub fn new_transaction_paths_msg(
        transaction_paths: Arc<TransactionPaths>,
        from: String,
    ) -> Message {
        Message::SendTransactionPaths {
            transaction_paths,
            from,
        }
    }

    pub fn new_generate_block_msg() -> Message {
        Message::GenerateBlock
    }

    pub fn new_generate_transaction_path_msg(to: String) -> Message {
        Message::GenerateTransactionPaths { to }
    }

    pub fn new_send_randao_seed_msg() -> Message {
        Message::SendRandaoSeed
    }

    pub fn new_receive_random_seed_msg(randao_seed: RandaoSeed) -> Message {
        Message::ReceiveRandaoSeed(randao_seed)
    }

    pub fn new_become_validator_msg(stake_map: std::collections::HashMap<String, f64>) -> Message {
        Message::BecomeValidator(stake_map)
    }

    pub fn new_receive_become_validator_msg(validator: Validator) -> Message {
        Message::ReceiveBecomeValidator(validator)
    }

    pub fn new_update_slot_msg(slot: SlotManager) -> Message {
        Message::UpdateSlot(slot)
    }

    pub fn new_print_blockchain_msg() -> Message {
        Message::PrintBlockchain
    }

    pub fn new_request_block_sync_msg(last_block_index: u64, from: String) -> Message {
        Message::RequestBlockSync {
            last_block_index,
            from,
        }
    }

    pub fn new_response_block_sync_msg(blocks: Vec<Block>, from: String) -> Message {
        Message::ResponseBlockSync { blocks, from }
    }

    pub fn new_update_validator_stake_msg(address: String, new_stake: f64) -> Message {
        Message::UpdateValidatorStake { address, new_stake }
    }

    pub fn new_update_node_balance_msg(new_balance: f64) -> Message {
        Message::UpdateNodeBalance(new_balance)
    }

    pub fn new_block_production_failed_msg(node_index: u32, slot: u64, reason: String) -> Message {
        Message::BlockProductionFailed {
            node_index,
            slot,
            reason,
        }
    }
}
