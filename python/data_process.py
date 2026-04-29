import json
import os
from dataclasses import dataclass, field
from typing import List

from dataclasses_json import dataclass_json, config


@dataclass_json
@dataclass
class Path:
    signature: str
    paths: List[str]


@dataclass_json
@dataclass
class Transaction:
    _from: str = field(metadata=config(field_name="from"))
    to: str
    amount: int
    hash: str
    signature: str
    timestamp: int


@dataclass_json
@dataclass
class Header:
    index: int
    epoch: int
    slot: int
    hash: str
    parent_hash: str
    timestamp: int
    merkle_root: str
    miner: str


@dataclass_json
@dataclass
class Body:
    transactions: List[Transaction]
    paths: List[Path]


@dataclass_json
@dataclass
class Block:
    header: Header
    body: Body


@dataclass_json
@dataclass
class Blockchain:
    blocks: List[Block]
    miners: dict[str, int]
    node_path: dict[str, int]
    edge_path: dict[str, int]

    def get_last_block(self) -> Block:
        return self.blocks[-1]

    def get_block_num(self) -> int:
        return len(self.blocks)

    def count_miners(self) -> dict[str, int]:
        miners: dict[str, int] = {}
        for block in self.blocks:
            if block.header.miner not in miners.keys():
                miners[block.header.miner] = 1
            else:
                miners[block.header.miner] += 1
        self.miners = miners
        return miners

    def get_miner_times(self, miner: str) -> int:
        if miner not in self.miners.keys():
            return 0
        return self.miners[miner]

    def get_miner_percentage(self, miner: str) -> float:
        return self.get_miner_times(miner) / self.get_block_num()

    def get_miner_top(self) -> str:
        return max(self.miners, key=lambda k: self.miners[k])

    def count_node_path(self) -> dict[str, int]:
        paths: dict[str, int] = {}
        for block in self.blocks:
            for path in block.body.paths:
                for p in path.paths:
                    if p not in paths:
                        paths[p] = 1
                    else:
                        paths[p] = paths[p] + 1
        self.node_path = paths
        return paths

    def get_node_path_times(self, node: str) -> int:
        if node not in self.node_path.keys():
            return 0
        return self.node_path[node]

    def get_node_path_percentage(self, node: str) -> float:
        s = sum(self.node_path.values())
        return self.get_node_path_times(node) / s

    def get_node_path_top(self) -> str:
        return max(self.node_path, key=lambda k: self.node_path[k])

    def count_edges_path(self) -> dict[str, int]:
        paths: dict[str, int] = {}
        for block in self.blocks:
            for path in block.body.paths:
                for i in range(len(path.paths) - 1):
                    s = path.paths[i] + ">" + path.paths[i + 1]
                    if s not in paths:
                        paths[s] = 1
                    else:
                        paths[s] = paths[s] + 1
        self.edge_path = paths
        return paths

    def get_edges(self) -> [[]]:
        edges: list[list[str]] = []
        if self.edge_path is None:
            self.count_edges_path()
        for x in self.edge_path.keys():
            nodes = x.split(">")
            edges.append([nodes[0], nodes[1]])
        return edges


def get_project_root():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    while current_dir != os.path.dirname(current_dir):
        if os.path.exists(os.path.join(current_dir, 'Cargo.toml')):
            return current_dir
        current_dir = os.path.dirname(current_dir)
    return current_dir


def get_blockchain_from_json(path=None):
    if path is None:
        project_root = get_project_root()
        path = os.path.join(project_root, 'blockchain.json')
    with open(path, 'r') as f:
        block_list = json.load(f)
    # 创世区块去掉
    blocks = [Block.from_dict(b) for b in block_list][1:]
    bc = Blockchain(blocks, {}, {}, {})
    bc.count_miners()
    bc.count_node_path()
    bc.count_edges_path()
    return bc


if __name__ == '__main__':
    bc = get_blockchain_from_json()
    print(bc.get_last_block())
    # 统计miners
    count_miners = bc.miners
    print('miner', len(count_miners.keys()))
    print('miner', count_miners)
    # 统计path
    count_node_path = bc.node_path
    print('node_path', len(count_node_path.keys()))
    print('node_path', count_node_path)
    # 统计边
    count_edges_path = bc.edge_path
    print('edges_path', len(count_edges_path.keys()))
    print('edges_path', count_edges_path)
    print('edges', bc.get_edges())

    print("top", bc.get_node_path_top())
    print("top", bc.get_node_path_percentage(bc.get_node_path_top()))
    print("miner top", bc.get_miner_top())
