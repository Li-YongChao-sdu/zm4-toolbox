// Coordinates follow the native client: y is the column, x grows bottom to top.
export const CELLS = [];
const lookup = new Map();
for (let y = 0; y < 7; y++) {
  for (let x = 0; x < 6; x++) {
    const visible = y === 0 || y === 6 ? x >= 2 && x <= 3
      : y === 1 || y === 5 ? x >= 1 && x <= 4 : true;
    if (visible) {
      const cell = {index: CELLS.length, x, y, row: 6 - x, column: y + 1};
      lookup.set(`${x},${y}`, cell.index);
      CELLS.push(cell);
    }
  }
}
export const cellIndex = (x, y) => lookup.get(`${x},${y}`);
export const TRIPLES = [];
for (const cell of CELLS) {
  for (const [dx, dy] of [[1, 0], [0, 1]]) {
    const b = cellIndex(cell.x + dx, cell.y + dy);
    const c = cellIndex(cell.x + 2 * dx, cell.y + 2 * dy);
    if (b !== undefined && c !== undefined) TRIPLES.push([cell.index, b, c]);
  }
}
export const VALUES = [0, 1, 3, 9, 27, 81, 243, 729, 2187, 6561];
export const DRAW_TABLE = [null,
  {levels: [1], weights: [1]},
  {levels: [1, 2], weights: [1, 1]},
  {levels: [1, 2, 3], weights: [1, 3, 2]},
  {levels: [2, 3, 4], weights: [1, 3, 2]},
  {levels: [3, 4, 5], weights: [1, 3, 2]},
  {levels: [3, 4, 5, 6], weights: [1, 3, 3, 2]},
  {levels: [4, 5, 6, 7], weights: [1, 3, 3, 2]},
  {levels: [5, 6, 7, 8], weights: [1, 3, 3, 2]},
  {levels: [5, 6, 7, 8], weights: [1, 1, 3, 3]},
];
export const ITEM_PROBABILITY = [0, 0, 0, 0, .05, .05, .10, .15, .15, .20];
export function stepProbability(step) {
  return step >= 80 ? .12 : step >= 50 ? .06 : step >= 30 ? .03 : 0;
}
export function boardMaximum(board) {
  let maximum = 1;
  for (const value of board) if (value > maximum) maximum = value;
  return maximum;
}
export function score(board) {
  let total = 0;
  for (const value of board) if (value > 0) total += VALUES[value];
  return total;
}
export function emptyCount(board) {
  let count = 0;
  for (const value of board) if (value === 0) count++;
  return count;
}
export function boardFromServer(ballPool) {
  return Int8Array.from(CELLS, ({x, y}) => integer(ballPool?.[y]?.[x] ?? 0, -1, 9, '格子等级'));
}
export function boardFromRows(rows) {
  if (!Array.isArray(rows) || rows.length !== 6 || rows.some(r => r.length !== 7)) {
    throw new Error('棋盘需要六行、每行七格。');
  }
  return Int8Array.from(CELLS, ({row, column}) => integer(rows[row - 1][column - 1] ?? 0, -1, 9, '格子等级'));
}
export function boardRows(board) {
  const rows = Array.from({length: 6}, () => Array(7).fill(null));
  CELLS.forEach(({row, column}, i) => { rows[row - 1][column - 1] = board[i]; });
  return rows;
}
function integer(value, minimum, maximum, name) {
  if (!Number.isInteger(value) || value < minimum || value > maximum) {
    throw new Error(`${name}应为${minimum}至${maximum}之间的整数。`);
  }
  return value;
}
export function normalizeState(input) {
  let board;
  if (input.ballPool) board = boardFromServer(input.ballPool);
  else if (input.rows) board = boardFromRows(input.rows);
  else if (input.board?.length === 30) {
    for (const value of input.board) integer(value, -1, 9, '格子等级');
    board = Int8Array.from(input.board);
  } else throw new Error('缺少三十格棋盘。');
  for (const value of board) integer(value, -1, 9, '格子等级');
  const state = {
    board,
    nextId: integer(input.nextId, 1, 9, '下颗丹药'),
    step: integer(input.step, 0, 100000, '当前步数'),
    clears: integer(input.clears ?? (3 - (input.jingDanNum ?? 0)), 0, 3, '剩余净丹露'),
    maxId: Math.max(boardMaximum(board), integer(input.maxId ?? 1, 1, 9, '最高等级')),
  };
  return state;
}
export function serializeState(state) {
  return {...state, board: Array.from(state.board)};
}
export function legalActions(state) {
  if (!emptyCount(state.board)) return [];
  const actions = [];
  state.board.forEach((value, index) => {
    if (value === 0) actions.push({type: 'place', index});
    else if (value === -1 && state.clears > 0) actions.push({type: 'clear', index});
  });
  return actions;
}
export function describeAction(action) {
  const position = CELLS[action.index];
  return {...action, ...position, label: `${action.type === 'clear' ? '清理' : '落子'}：第${position.row}行，第${position.column}列`};
}
export function findTriple(board) {
  for (const triple of TRIPLES) {
    const level = board[triple[0]];
    if (level > 0 && level < 9 && level === board[triple[1]] && level === board[triple[2]]) return triple;
  }
  return null;
}
export function mergeAt(board, triple) {
  const level = ++board[triple[0]];
  board[triple[1]] = board[triple[2]] = 0;
  return level;
}
export function deterministicMove(state, action) {
  const result = {...state, board: state.board.slice(), step: state.step + 1};
  if (!emptyCount(state.board)) throw new Error('棋盘已满，本局已结束。');
  if (action.type === 'clear') {
    if (!state.clears || result.board[action.index] !== -1) throw new Error('该格不能清理。');
    result.board[action.index] = 0;
    result.clears--;
    return {state: result, merges: []};
  }
  if (action.type !== 'place' || result.board[action.index] !== 0) throw new Error('只能在空格落子。');
  result.board[action.index] = state.nextId;
  const merges = [];
  for (let triple; (triple = findTriple(result.board));) {
    const level = mergeAt(result.board, triple);
    result.maxId = Math.max(result.maxId, level);
    merges.push({indices: triple, level, maxId: result.maxId});
  }
  result.maxId = Math.max(result.maxId, state.nextId);
  return {state: result, merges};
}
export function drawLevel(maxId, random) {
  const {levels, weights} = DRAW_TABLE[maxId];
  let value = random() * weights.reduce((a, b) => a + b, 0);
  for (let i = 0; i < levels.length; i++) {
    value -= weights[i];
    if (value < 0) return levels[i];
  }
  return levels.at(-1);
}
export function expectedDraw(maxId) {
  const {levels, weights} = DRAW_TABLE[maxId];
  return weights.reduce((sum, w, i) => sum + w * VALUES[levels[i]], 0) / weights.reduce((a, b) => a + b, 0);
}
function addSlag(board, probability, random) {
  if (probability <= 0 || random() >= probability) return;
  let empties = emptyCount(board);
  if (!empties) return;
  let target = Math.min(empties - 1, Math.floor(random() * empties));
  for (let index = 0; index < board.length; index++) {
    if (board[index] === 0 && target-- === 0) { board[index] = -1; return; }
  }
}
// A working probability model; the native server's random implementation is unknown.
export function randomMove(state, action, random, options = {}) {
  if (action.type === 'clear') return deterministicMove(state, action).state;
  if (state.board[action.index] !== 0 || !emptyCount(state.board)) throw new Error('不能在该格落子。');
  const result = {...state, board: state.board.slice(), step: state.step + 1};
  result.board[action.index] = state.nextId;
  result.maxId = Math.max(result.maxId, state.nextId);
  const model = options.mergeModel ?? 'current_max';
  const finalMax = model === 'final_max' ? deterministicMove(state, action).state.maxId : 0;
  for (let triple; (triple = findTriple(result.board));) {
    const level = mergeAt(result.board, triple);
    result.maxId = Math.max(result.maxId, level);
    const key = model === 'new_grade' ? level : model === 'final_max' ? finalMax : result.maxId;
    addSlag(result.board, ITEM_PROBABILITY[key], random);
  }
  addSlag(result.board, stepProbability(options.stepBefore ? state.step : result.step), random);
  result.nextId = drawLevel(result.maxId, random);
  return result;
}
// Replay uses the recorded random outcomes, and checks each merge at its actual phase.
export function replayMove(state, action, log, afterNextId) {
  if (action.type === 'clear') return deterministicMove(state, action).state;
  const result = {...state, board: state.board.slice(), step: state.step + 1};
  if (result.board[action.index] !== 0) throw new Error('回放落子格非空。');
  result.board[action.index] = state.nextId;
  result.maxId = Math.max(result.maxId, state.nextId);
  for (const event of log ?? []) {
    if (event.merge) {
      const triple = findTriple(result.board);
      const expected = [cellIndex(event.merge.x, event.merge.y), ...event.eli.map(e => cellIndex(e.x, e.y))];
      if (!triple || triple.some((cell, i) => cell !== expected[i])) throw new Error('合成顺序与原始回包不同。');
      const level = mergeAt(result.board, triple);
      if (level !== event.merge.v) throw new Error('合成等级不同。');
      result.maxId = Math.max(result.maxId, level);
    }
    if (event.failed) {
      const index = cellIndex(event.failed.x, event.failed.y);
      if (index === undefined || result.board[index] !== 0) throw new Error('丹渣目标不是空格。');
      result.board[index] = -1;
    }
  }
  if (findTriple(result.board)) throw new Error('回包漏掉可合成的三连。');
  result.nextId = afterNextId ?? state.nextId;
  return result;
}
