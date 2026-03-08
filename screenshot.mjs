import puppeteer from 'puppeteer-core';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const url   = process.argv[2] || 'http://localhost:3000';
const label = process.argv[3] || '';

// Chrome path
const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';

// Auto-increment filename
const screenshotsDir = path.join(__dirname, 'temporary screenshots');
if (!fs.existsSync(screenshotsDir)) fs.mkdirSync(screenshotsDir, { recursive: true });

function nextFilename() {
  const files = fs.existsSync(screenshotsDir)
    ? fs.readdirSync(screenshotsDir).filter(f => f.endsWith('.png'))
    : [];
  let max = 0;
  for (const f of files) {
    const m = f.match(/^screenshot-(\d+)/);
    if (m) max = Math.max(max, parseInt(m[1]));
  }
  const n    = String(max + 1).padStart(3, '0');
  const name = label ? `screenshot-${n}-${label}.png` : `screenshot-${n}.png`;
  return path.join(screenshotsDir, name);
}

(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
  });

  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900 });
  await page.goto(url, { waitUntil: 'networkidle2', timeout: 30000 });

  // Wait for fonts
  await new Promise(r => setTimeout(r, 1500));

  const outPath = nextFilename();
  await page.screenshot({ path: outPath, fullPage: true });
  console.log('Screenshot saved:', outPath);

  await browser.close();
})();
