import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

// Load the real calculations with inert browser/data dependencies.
const moduleURL = (source) => `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`;
const source = (await readFile(new URL('../static/kwd/js/fr.js', import.meta.url), 'utf8'))
  .replace("'./core.js'", JSON.stringify(moduleURL('export const supabase = {};')))
  .replace("'./lib.js'", JSON.stringify(moduleURL('export const istDate = () => "2026-10-30"; export const addDays = () => {};')));
const { achievement } = await import(moduleURL(source));
const month = '2026-10-01';
const row = (franchise_id, product_id, target_units) => ({ month, franchise_id, product_id, target_units });

test('product targets supersede legacy overall units, including zero', () => {
  const targets = [row('a', null, 100), row('a', 'iron', 10), row('a', 'paper', 20)];
  assert.equal(achievement([], targets, month, 'a').tUnits, 30);
  targets[0].target_amount = 60000;
  assert.equal(achievement([], targets, month, 'a').tValue, 0);
  assert.equal(achievement([], [row('a', null, 100), row('a', 'iron', 0)], month, 'a').tUnits, 0);
});

test('mixed franchises retain their own product or legacy fallback targets', () => {
  const targets = [row('a', null, 100), row('a', 'iron', 10), row('b', null, 20)];
  assert.equal(achievement([], targets, month).tUnits, 30);
  assert.equal(achievement([], targets, month, 'b').tUnits, 20);
  assert.equal(achievement([], targets, '2026-11-01').tUnits, 0);
});

const coreStubURL = moduleURL(`
  export const requests = [];
  export const html = () => '', raw = x => x, errText = x => x, toast = () => {};
  export const supabase = { from(table) { return {
    update(values) { this.op = 'update'; this.values = values; return this; },
    delete() { this.op = 'delete'; return this; },
    eq(key, id) { requests.push({ table, op: this.op, values: this.values, id }); return { error: null }; },
    insert(values) { requests.push({ table, op: 'insert', values }); return { error: null }; }
  }; } };
`);
const { requests } = await import(coreStubURL);
const targetsSource = (await readFile(new URL('../static/kwd/js/pages/ho/fr/targets.js', import.meta.url), 'utf8'))
  .replace("'../../../core.js'", JSON.stringify(coreStubURL))
  .replace("'../../../fr.js'", JSON.stringify(moduleURL(source)))
  .replace("'../../../ui.js'", JSON.stringify(moduleURL('export const Loading=()=>{}, Icon=()=>{}, PageHead=()=>{}, SectionHead=()=>{};')))
  .replace("'../../../kit.js'", JSON.stringify(moduleURL('export const Sheet=()=>{}, errLine=()=>{};')))
  .replace("'../../../lib.js'", JSON.stringify(moduleURL('export const fmtINR=x=>x;')));
const { default: page } = await import(moduleURL(targetsSource));

test('clearing product targets removes the hidden legacy overall target', async () => {
  requests.length = 0;
  const screen = {
    S: { month, pf: 'a', pt: { iron: '', retired: 9 }, busy: false,
      d: { targets: [{ ...row('a', null, 100), id: 'legacy' }, { ...row('a', 'iron', 10), id: 'product' }] } },
    ctx: { data: { products: [{ id: 'iron', is_active: true }, { id: 'retired', is_active: false }] } },
    set(values) { Object.assign(this.S, values); }, actions: { load: async () => {} },
  };
  await page.actions.saveProducts.call(screen);
  assert.deepEqual(requests.map(({ op, id }) => ({ op, id })), [{ op: 'delete', id: 'product' }, { op: 'delete', id: 'legacy' }]);
  requests.length = 0;
  screen.S.pt.iron = '1.5';
  await page.actions.saveProducts.call(screen);
  assert.equal(requests.length, 0);
});
