import { test, expect } from '../support/auth-fixture';
import { HomePage } from '../pages/home.page';

type NavSnapshot = {
  width: number;
  stageCount: number;
  stages: string[];
  leftSpace: number;
  gap12: number;
  gap23: number;
  gap34: number;
  rightSpace: number;
  x1: number;
  x2: number;
  x3: number;
  x4: number;
  y1: number;
  y2: number;
  y3: number;
  y4: number;
  control1Width: number;
  labels: {
    home: boolean;
    admin: boolean;
    user: boolean;
  };
};

const NAV_WIDTHS = [
  1500, 1320, 1240, 1160, 1100, 1040, 980, 940, 900, 880, 860, 840, 820, 800, 760, 720, 680, 640, 600, 560, 520, 460, 420, 380, 360, 340, 320, 300,
  280, 260,
];

async function captureNavSnapshot(page: any, width: number): Promise<NavSnapshot> {
  await page.setViewportSize({ width, height: 900 });
  await page.waitForTimeout(120);

  return page.evaluate((snapshotWidth) => {
    const topInner = document.querySelector('.top-inner');
    if (!topInner) {
      throw new Error('missing .top-inner');
    }
    const topInnerBox = topInner.getBoundingClientRect();
    const stages = [...(topInner?.classList ?? [])]
      .filter((token) => token.startsWith('nav-stage-'))
      .sort();
    const controls = Array.from(
      document.querySelectorAll(
        '.top-inner .header-left > .home-link, .top-inner .header-left .admin-links > .menu-action, .top-inner .login-info .user-menu > summary'
      )
    );
    if (controls.length < 4) {
      throw new Error(`expected 4 nav controls but found ${controls.length}`);
    }
    const boxes = controls.map((control) => control.getBoundingClientRect());

    const visible = (selector: string): boolean => {
      const node = document.querySelector(selector);
      if (!node) {
        return false;
      }
      return window.getComputedStyle(node).display !== 'none';
    };

    return {
      width: snapshotWidth,
      stageCount: stages.length,
      stages,
      leftSpace: boxes[0].left - topInnerBox.left,
      gap12: boxes[1].left - boxes[0].right,
      gap23: boxes[2].left - boxes[1].right,
      gap34: boxes[3].left - boxes[2].right,
      rightSpace: topInnerBox.right - boxes[3].right,
      x1: boxes[0].left,
      x2: boxes[1].left,
      x3: boxes[2].left,
      x4: boxes[3].left,
      y1: boxes[0].top,
      y2: boxes[1].top,
      y3: boxes[2].top,
      y4: boxes[3].top,
      control1Width: boxes[0].width,
      labels: {
        home: visible('.home-link .home-link-label'),
        admin: visible('.admin-links .menu-action .menu-action-label'),
        user: visible('.user-menu summary > span'),
      },
    };
  }, width);
}

async function sampleNavSnapshots(page: any, homePage: HomePage): Promise<NavSnapshot[]> {
  await homePage.goto();
  await page.locator('.top-inner').first().waitFor({ state: 'visible' });
  const snapshots: NavSnapshot[] = [];
  for (const width of NAV_WIDTHS) {
    snapshots.push(await captureNavSnapshot(page, width));
  }
  return snapshots;
}

function stageSnapshot(snapshots: NavSnapshot[], stageCount: number): NavSnapshot {
  const found = snapshots.find((snapshot) => snapshot.stageCount === stageCount);
  if (!found) {
    throw new Error(`missing nav stage ${stageCount}`);
  }
  return found;
}

function stageSnapshots(snapshots: NavSnapshot[], stageCount: number): NavSnapshot[] {
  return snapshots.filter((snapshot) => snapshot.stageCount === stageCount);
}

test.describe('Home Page', () => {
  let homePage: HomePage;

  test.beforeEach(async ({ page }) => {
    homePage = new HomePage(page);
  });

  test('should display all navigation links', async () => {
    await homePage.verifyAllLinksVisible();
  });

  test('should allow skipping to main content', async () => {
    await homePage.clickSkipToMainContent();
  });

  test('should apply nav compression phases in the requested sequence', async ({ page }) => {
    test.slow();
    const snapshots = await sampleNavSnapshots(page, homePage);

    const expanded = stageSnapshot(snapshots, 0);
    const centerStages = stageSnapshots(snapshots, 1);
    if (centerStages.length === 0) {
      throw new Error('missing nav stage 1');
    }
    const centerEqual = centerStages[centerStages.length - 1];
    const centerStart = centerStages[0];
    const iconAnchored = stageSnapshot(snapshots, 2);
    const finalCompressed = stageSnapshot(snapshots, 3);

    expect(centerEqual.width).toBeLessThan(expanded.width);
    expect(iconAnchored.width).toBeLessThan(centerEqual.width);
    expect(finalCompressed.width).toBeLessThan(iconAnchored.width);

    expect(expanded.labels.home).toBe(true);
    expect(expanded.labels.admin).toBe(true);
    expect(expanded.labels.user).toBe(true);
    expect(expanded.gap34).toBeGreaterThan(expanded.gap23 + 16);
    expect(expanded.rightSpace).toBeLessThan(24);

    expect(centerEqual.labels.home).toBe(true);
    expect(centerEqual.labels.admin).toBe(true);
    expect(centerEqual.labels.user).toBe(true);
    expect(centerEqual.gap34).toBeLessThan(expanded.gap34 - 120);
    expect(centerEqual.gap34).toBeLessThan(140);
    expect(centerEqual.rightSpace).toBeLessThan(24);
    expect(centerEqual.gap34).toBeLessThan(centerStart.gap34 + 1);

    expect(iconAnchored.labels.home).toBe(false);
    expect(iconAnchored.labels.admin).toBe(false);
    expect(iconAnchored.labels.user).toBe(false);
    expect(iconAnchored.gap34).toBeGreaterThan(centerEqual.gap34 + 80);
    expect(iconAnchored.rightSpace).toBeLessThan(24);

    expect(finalCompressed.labels.home).toBe(false);
    expect(finalCompressed.labels.admin).toBe(false);
    expect(finalCompressed.labels.user).toBe(false);
    expect(Math.abs(finalCompressed.gap34 - finalCompressed.gap23)).toBeLessThan(3);
    expect(finalCompressed.gap34).toBeLessThan(iconAnchored.gap34 - 24);
    expect(Math.abs(finalCompressed.leftSpace - finalCompressed.rightSpace)).toBeLessThan(4);
    expect(finalCompressed.control1Width).toBeLessThan(iconAnchored.control1Width - 0.5);

    for (const snapshot of [expanded, centerEqual, iconAnchored, finalCompressed]) {
      expect(Math.abs(snapshot.y1 - snapshot.y2)).toBeLessThan(4);
      expect(Math.abs(snapshot.y2 - snapshot.y3)).toBeLessThan(4);
      expect(Math.abs(snapshot.y3 - snapshot.y4)).toBeLessThan(4);
      expect(snapshot.gap12).toBeGreaterThan(-0.5);
      expect(snapshot.gap23).toBeGreaterThan(-0.5);
      expect(snapshot.gap34).toBeGreaterThan(-0.5);
      expect(snapshot.x1).toBeLessThan(snapshot.x2);
      expect(snapshot.x2).toBeLessThan(snapshot.x3);
      expect(snapshot.x3).toBeLessThan(snapshot.x4);
    }
  });

  test('should debounce homepage search and enforce show-more reset/reveal timing', async ({ page }) => {
    await homePage.goto();

    const visibleItems = (section: 'devices' | 'groups') =>
      page.locator(`[data-home-section="${section}"] li[data-home-item="true"]:not([hidden])`);

    const resolveSectionState = async () => {
      return page.evaluate(() => {
        const sections: Array<'devices' | 'groups'> = ['devices', 'groups'];
        for (const section of sections) {
          const rows = Array.from(document.querySelectorAll(`[data-home-section="${section}"] li[data-home-item="true"]`));

          if (rows.length <= 5) {
            continue;
          }

          const counts: Record<string, number> = {};
          for (const row of rows) {
            const name = String(row.getAttribute('data-home-item-name') || '').trim().toLowerCase();
            if (!name) {
              continue;
            }

            const key = name[0];
            counts[key] = (counts[key] || 0) + 1;
          }

          const candidate = Object.entries(counts).find(([, total]) => total > 5);
          if (candidate) {
            return {
              section,
              prefix: candidate[0],
              matchCount: candidate[1],
            };
          }
        }
        return null;
      });
    };

    const scenario = await resolveSectionState();
    if (scenario == null) {
      test.skip('No section has a single-character filter with more than five matches.');
    }

    const showMoreButton = page.locator(scenario!.section === 'devices' ? '#home-devices-show-more' : '#home-groups-show-more');
    const searchInput = page.locator(scenario!.section === 'devices' ? '#home-device-search' : '#home-group-search');

    await expect(showMoreButton).toBeVisible();
    expect(await visibleItems(scenario!.section).count()).toBe(5);
    await expect(searchInput).toBeVisible();

    await searchInput.fill(scenario!.prefix);
    await expect(showMoreButton).toBeHidden();

    await page.waitForTimeout(250);
    expect(await visibleItems(scenario!.section).count()).toBeLessThanOrEqual(scenario!.matchCount);

    await page.waitForTimeout(2050);
    await expect(showMoreButton).toBeVisible();

    await showMoreButton.click();
    expect(await visibleItems(scenario!.section).count()).toBeGreaterThan(5);

    await searchInput.fill('');
    await expect(showMoreButton).toBeHidden();
    await page.waitForTimeout(250);
    expect(await visibleItems(scenario!.section).count()).toBe(5);
    await page.waitForTimeout(2050);
    await expect(showMoreButton).toBeVisible();
  });

  test('should log out and redirect to login page', async ({ page }) => {
    await homePage.openUserMenu();
    await page.getByRole('button', { name: 'Logout' }).click();
    await expect(page).toHaveURL(/\/auth\/login(?:\?.*)?$/);
    await expect(page.getByRole('button', { name: /Login with NIH Credentials/i })).toBeVisible();
  });
});
