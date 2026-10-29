import type { TestInfo } from '@playwright/test';

function hashToBase36(seed: string): string {
  let hash = 2166136261;
  for (let index = 0; index < seed.length; index += 1) {
    hash ^= seed.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(36).padStart(6, '0').slice(0, 6);
}

export function mockSessionKeyFor(testInfo: TestInfo): string {
  return hashToBase36(`${testInfo.project.name}:${testInfo.testId}`);
}
