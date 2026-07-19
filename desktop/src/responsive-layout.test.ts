// @ts-expect-error Vitest runs in Node; production desktop types intentionally omit Node.
import { readFileSync } from "node:fs";
import { expect, it } from "vitest";

const styles = readFileSync("src/styles.css", "utf8");

it("keeps Cockpit chrome and controls contained when resize or page zoom reduces space", () => {
  expect(styles).toMatch(/\.app-sidebar\s*\{[^}]*min-height:\s*0;[^}]*overflow:\s*hidden;/s);
  expect(styles).toMatch(/\.app-sidebar nav\s*\{[^}]*min-height:\s*0;[^}]*overflow-y:\s*auto;/s);
  expect(styles).toMatch(/\.composer-controls\s*\{[^}]*max-width:\s*100%;[^}]*flex-wrap:\s*wrap;/s);
  expect(styles).toContain("@media (max-height: 800px)");
  expect(styles).toMatch(/@media \(max-height: 800px\)[\s\S]*\.conversation-header\s*\{[^}]*height:\s*88px;/);
});

it("does not retain Watch inference popover rules", () => {
  expect(styles).not.toMatch(/\.inference(?:-|[\s.{:#])/);
  expect(styles).not.toMatch(/\.state-assessment-panel|\.state-inference-grid/);
});

it("reflows Watch from its content width instead of the full Cockpit viewport", () => {
  expect(styles).toMatch(/\.watch-content\s*\{[^}]*container-type:\s*inline-size;/s);
  expect(styles).toMatch(/\.oauth-source-grid\s*\{[^}]*repeat\(auto-fit,\s*minmax\(min\(100%,\s*260px\),\s*1fr\)\)/s);
  expect(styles).toMatch(/@container\s*\(max-width:\s*900px\)[\s\S]*\.summary-layout\s*\{[^}]*grid-template-columns:\s*1fr;/s);
  expect(styles).toMatch(/@container\s*\(min-width:\s*561px\)\s*and\s*\(max-width:\s*839px\)[\s\S]*\.oauth-source-section:last-child\s*\{[^}]*grid-column:\s*1\s*\/\s*-1;/s);
  expect(styles).toMatch(/@container\s*\(max-width:\s*760px\)[\s\S]*\.watch-overview-grid\s*\{[^}]*grid-template-columns:\s*1fr;/s);
});

it("keeps Watch metadata above the previous 7 to 9 pixel readability floor", () => {
  expect(styles).toMatch(/\.watch-view p,\s*\.watch-view span,\s*\.watch-view dd\s*\{\s*font-size:\s*11px;/s);
  expect(styles).toMatch(/\.watch-view small,\s*\.watch-view dt,\s*\.watch-view code,\s*\.watch-view time,\s*\.watch-view footer\s*\{\s*font-size:\s*10px;/s);
  expect(styles).toMatch(/\.watch-view \.watch-timeline strong\s*\{\s*font-size:\s*12px;/s);
  expect(styles).toMatch(/\.watch-view \.watch-data-boundary strong\s*\{\s*font-size:\s*10px;/s);
});
