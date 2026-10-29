import { test, expect } from '@playwright/test';

function headerValues(response: { headersArray(): Array<{ name: string; value: string }> }, name: string): string[] {
  const target = name.toLowerCase();
  return response
    .headersArray()
    .filter((header) => header.name.toLowerCase() === target)
    .map((header) => header.value);
}

test.describe('Edge Security Headers', () => {
  test('should expose a single CSP authority with scheme-aware transport headers', async ({ request }) => {
    const response = await request.get('/auth/login');

    expect(response.ok()).toBeTruthy();

    const xContentTypeOptions = headerValues(response, 'x-content-type-options');
    const xFrameOptions = headerValues(response, 'x-frame-options');
    const referrerPolicy = headerValues(response, 'referrer-policy');
    const csp = headerValues(response, 'content-security-policy');
    const cspReportOnly = headerValues(response, 'content-security-policy-report-only');
    const reportingEndpoints = headerValues(response, 'reporting-endpoints');
    const hsts = headerValues(response, 'strict-transport-security');

    expect(xContentTypeOptions).toEqual(['nosniff']);
    expect(xFrameOptions).toEqual(['DENY']);
    expect(referrerPolicy).toEqual(['strict-origin-when-cross-origin']);
    expect(csp.length + cspReportOnly.length).toBe(1);

    const effectiveCsp = csp[0] ?? cspReportOnly[0] ?? '';
    expect(effectiveCsp).toContain("default-src 'self'");
    expect(effectiveCsp).toContain("script-src 'self'");
    expect(effectiveCsp).toContain("'strict-dynamic'");
    expect(effectiveCsp).toMatch(/script-src[^;]*'nonce-[^']+'/);
    expect(effectiveCsp).toContain("script-src-attr 'none'");
    expect(effectiveCsp).toContain("style-src 'self'");
    expect(effectiveCsp).toContain("style-src-attr 'none'");
    expect(effectiveCsp).toContain('report-to csp-endpoint');
    expect(reportingEndpoints).toContain('csp-endpoint="/csp-report"');
    expect(effectiveCsp).not.toContain("'unsafe-inline'");
    expect(effectiveCsp).not.toContain('{nonce}');

    const isHttps = new URL(response.url()).protocol === 'https:';
    if (isHttps) {
      expect(hsts).toHaveLength(1);
      expect(hsts[0]).toContain('max-age=');
    } else {
      expect(hsts).toEqual([]);
    }
  });
});
