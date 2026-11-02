"""Standalone deterministic inference for the small-freeze-penalty policy.

Only torch and Python's standard library are required. No training imports.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Mapping

import torch

VALID = tuple((y, x) for y in range(7)
              for x in ((2, 3) if y in (0, 6) else
                        (1, 2, 3, 4) if y in (1, 5) else (0, 1, 2, 3, 4, 5)))
ACTIONS = list(VALID) + [('water', y, x) for y, x in VALID] + [('end',)]


class ActorCritic(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.body = torch.nn.Sequential(torch.nn.Linear(343, 256), torch.nn.Tanh(),
                                        torch.nn.Linear(256, 256), torch.nn.Tanh())
        self.policy = torch.nn.Linear(256, 61)
        self.critic = torch.nn.Linear(256, 1)

    def forward(self, obs, mask):
        hidden = self.body(obs)
        logits = self.policy(hidden).masked_fill(~mask, -1e9)
        dist = torch.distributions.Categorical(logits=logits, validate_args=False)
        return dist, self.critic(hidden).squeeze(-1)


def _integer(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f'{name} must be an integer in [{low}, {high}]')
    return value


def normalize_state(state: Mapping):
    """Accept the original environment observe() dict or the documented JSON."""
    board = state.get('board')
    if board is None:
        matrix = state.get('board2d')
        if not isinstance(matrix, (list, tuple)) or len(matrix) != 7 or any(
                not isinstance(row, (list, tuple)) or len(row) != 6 for row in matrix):
            raise ValueError('Supply board[30] or board2d[7][6]')
        board = [matrix[y][x] for y, x in VALID]
    if not isinstance(board, (list, tuple)) or len(board) != 30:
        raise ValueError('board must contain exactly 30 cells in VALID order')
    board = [_integer(v, f'board[{i}]', -1, 9) for i, v in enumerate(board)]
    maximum = _integer(state['max_level'], 'max_level', 1, 9)
    next_level = _integer(state['next_level'], 'next_level', 1, 9)
    if max(board) > maximum or next_level > maximum:
        raise ValueError('max_level is the historical maximum and cannot be below current pills')
    water = _integer(state['water_left'], 'water_left', 0, 3)
    score = _integer(state['score'], 'score', 0, 2**53-1)
    time_left = state['time_left']
    if isinstance(time_left, bool) or not isinstance(time_left, (int, float)) or not math.isfinite(time_left) or not 0 <= time_left <= 300:
        raise ValueError('time_left must be finite seconds in [0, 300]')
    done = state.get('done', False)
    if not isinstance(done, bool):
        raise ValueError('done must be a boolean')
    return board, next_level, maximum, water, score, float(time_left), done


class Predictor:
    """Load once, then reuse predict() for every game action. CPU is the default."""
    def __init__(self, model_path=None, device='cpu'):
        self.model_path = Path(model_path) if model_path else Path(__file__).with_name('model.pt')
        self.model = ActorCritic()
        checkpoint = torch.load(self.model_path, map_location='cpu', weights_only=True)
        if checkpoint.get('format') != 'jiuzhuan-freeze-small-v1':
            raise ValueError('Unsupported inference-weight format')
        self.model.load_state_dict(checkpoint['model'], strict=True)
        self.model.eval()
        self.to(device)

    def to(self, device='cpu'):
        """Switch the same loaded weights at runtime: predictor.to('cpu')."""
        selected = torch.device(device)
        if selected.type not in ('cpu', 'cuda'):
            raise ValueError('Use cpu, cuda, or cuda:N')
        if selected.type == 'cuda' and not torch.cuda.is_available():
            raise RuntimeError('CUDA unavailable; select device="cpu"')
        self.model.to(selected)
        self.device = selected
        self.eye_board = torch.eye(11, device=selected)
        self.eye_level = torch.eye(9, device=selected)
        return self

    def encode(self, state):
        board, next_level, maximum, water, score, time_left, done = normalize_state(state)
        b = torch.tensor(board, dtype=torch.long, device=self.device)
        obs = torch.cat((self.eye_board[b+1].flatten(), self.eye_level[next_level-1],
            torch.tensor([maximum/9, water/3, min(score/45000, 1), time_left/300],
                         dtype=torch.float32, device=self.device)))
        mask = torch.cat((b == 0, (b == -1) & (water > 0),
                          torch.tensor([score >= 45000], device=self.device)))
        terminal = done or time_left <= 0 or score >= 45000 or 0 not in board
        return obs, mask, terminal

    @torch.inference_mode()
    def predict(self, state, include_probabilities=False):
        obs, mask, terminal = self.encode(state)
        if terminal:
            return dict(action_index=60, type='end', env_action=['end'], reason='terminal_or_target_reached')
        dist, _ = self.model(obs[None], mask[None])
        index = int(dist.logits.argmax(-1).item())
        result = dict(action_index=index, type='place' if index < 30 else 'water',
                      cell_index=index if index < 30 else index-30,
                      position=dict(y=VALID[index % 30][0], x=VALID[index % 30][1]),
                      env_action=list(ACTIONS[index]),
                      probability=float(dist.probs[0, index].item()))
        if include_probabilities:
            probabilities = dist.probs[0].cpu().tolist()
            legal = mask.cpu().tolist()
            result['legal_actions'] = [dict(action_index=i, env_action=list(ACTIONS[i]), probability=probabilities[i])
                                       for i, valid in enumerate(legal) if valid]
        return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model', type=Path, default=Path(__file__).with_name('model.pt'))
    p.add_argument('--device', default='cpu', help='cpu (default), cuda, or cuda:N')
    p.add_argument('--threads', type=int, default=1, help='CPU intra-op threads')
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument('--state', help='JSON file, or - for stdin')
    group.add_argument('--stream', action='store_true', help='One input JSON state and output action per line')
    p.add_argument('--probabilities', action='store_true')
    args = p.parse_args()
    if args.threads < 1:
        p.error('--threads must be positive')
    torch.set_num_threads(args.threads)
    predictor = Predictor(args.model, args.device)
    def handle(raw):
        try:
            state = json.loads(raw)
            if not isinstance(state, dict):
                raise ValueError('State must be a JSON object')
            return predictor.predict(state, args.probabilities)
        except (ValueError, KeyError, TypeError) as error:
            return dict(error=str(error))
    if args.stream:
        for line in sys.stdin:
            if line.strip():
                print(json.dumps(handle(line), ensure_ascii=False), flush=True)
    else:
        raw = sys.stdin.read() if args.state == '-' else Path(args.state).read_text(encoding='utf-8-sig')
        result = handle(raw)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if 'error' in result:
            raise SystemExit(2)


if __name__ == '__main__':
    main()
