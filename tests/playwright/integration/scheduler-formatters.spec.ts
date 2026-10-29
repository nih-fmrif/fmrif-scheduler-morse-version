import { test, expect } from '../support/auth-fixture';
import { waitForAppShell } from '../utils/test-helpers';

test.describe('Scheduler Formatters', () => {
  test('escapes formatter values instead of injecting markup', async ({ page }) => {
    await page.goto('/');
    await waitForAppShell(page);

    const result = await page.evaluate(async () => {
      const { fmt_log, fmt_editor_diffs, fmt_save_results } = await import(
        '/static/js/scheduler-editor/formatters.js'
      );

      const logHost = document.createElement('div');
      logHost.append(
        fmt_log({
          template: {
            id: '<img src=x onerror=window.__xss_id=1>',
            label: '<script>window.__xss_label=1</script>',
            hidden: true,
          },
          entries: [
            {
              modified: '2026-01-01T00:00:00Z',
              by: '<img src=x onerror=window.__xss_by=1>',
              kind: 'main',
              values: {
                group: ['old <b>tag</b>', 'new <i>tag</i>'],
                note: ['<script>bad()</script>', '<img src=x>'],
              },
            },
          ],
        })
      );

      const [notify, diffNode] = fmt_editor_diffs(
        { '9': '09:00' },
        false,
        [
          {
            date: '1',
            hour: '9',
            group: ['', '<img src=x onerror=window.__xss_group=1>'],
            member: ['old <script>bad()</script>', 'new <b>ok</b>'],
          },
        ]
      );
      const diffHost = document.createElement('div');
      diffHost.append(diffNode);

      const cellRecord = {
        date: '1',
        hour: '9',
        resetAndLock() {},
      };
      const saveHost = document.createElement('div');
      saveHost.append(
        fmt_save_results(
          {
            saved: 0,
            errors: {
              c1: [
                {
                  type: 'overwrote',
                  key: 'group',
                  expected: '<old>',
                  got: '<new>',
                },
              ],
            },
          },
          new Map([['c1', cellRecord]]),
          { '9': '09:00' }
        )
      );

      const anyInjected =
        logHost.querySelector('script, img') != null ||
        diffHost.querySelector('script, img') != null ||
        saveHost.querySelector('script, img') != null;

      return {
        notify,
        anyInjected,
        logText: logHost.textContent ?? '',
        diffText: diffHost.textContent ?? '',
        saveText: saveHost.textContent ?? '',
      };
    });

    expect(result.notify).toBe(true);
    expect(result.anyInjected).toBe(false);
    expect(result.logText).toContain('<img src=x onerror=window.__xss_id=1>');
    expect(result.logText).toContain('<script>window.__xss_label=1</script>');
    expect(result.diffText).toContain('<img src=x onerror=window.__xss_group=1>');
    expect(result.saveText).toContain('<old>');
    expect(result.saveText).toContain('<new>');
  });

  test('allows schedule elements and rejects unsafe payload markup', async ({ page }) => {
    await page.goto('/');
    await waitForAppShell(page);

    const result = await page.evaluate(async () => {
      const { parse_schedule_cell_markup } = await import(
        '/static/js/scheduler-editor/formatters.js'
      );

      const allowed = parse_schedule_cell_markup(
        '<entry-cell data-id="1"></entry-cell>'
      ).length;
      const pair = parse_schedule_cell_markup(
        '<entry-legend class="swatch-group-none"></entry-legend><entry-cell data-id="2"></entry-cell>'
      );
      const pairTags = pair.map((node) => node.tagName.toLowerCase());

      let scriptError = '';
      let textError = '';
      try {
        parse_schedule_cell_markup('<script>alert("xss")</script>');
      } catch (err) {
        scriptError = String((err as Error).message ?? err);
      }
      try {
        parse_schedule_cell_markup('unsafe raw text');
      } catch (err) {
        textError = String((err as Error).message ?? err);
      }

      return { allowed, pairTags, scriptError, textError };
    });

    expect(result.allowed).toBe(1);
    expect(result.pairTags).toEqual(['entry-legend', 'entry-cell']);
    expect(result.scriptError).toContain('disallowed element');
    expect(result.textError).toContain('unexpected text');
  });
});
