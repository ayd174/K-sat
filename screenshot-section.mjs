// Capture a viewport-sized screenshot at a specific scroll position
import puppeteer from 'puppeteer-core';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const url   = process.argv[2] || 'http://localhost:3000';
const yArg  = parseInt(process.argv[3] || '0', 10);
const label = process.argv[4] || 'sec';
const lang  = process.argv[5]; // optional FR/EN/NL/TR

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const screenshotsDir = path.join(__dirname, 'temporary screenshots');

function nextFilename() {
  const files = fs.readdirSync(screenshotsDir).filter(f => f.endsWith('.png'));
  let max = 0;
  for (const f of files) { const m = f.match(/^screenshot-(\d+)/); if (m) max = Math.max(max, parseInt(m[1])); }
  const n = String(max + 1).padStart(3, '0');
  return path.join(screenshotsDir, `screenshot-${n}-${label}.png`);
}

(async () => {
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: true, args: ['--no-sandbox'] });
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900 });
  if (lang) {
    await page.evaluateOnNewDocument((l) => { localStorage.setItem('ksat-lang', l); }, lang);
  }
  await page.goto(url, { waitUntil: 'networkidle2', timeout: 30000 });
  await new Promise(r => setTimeout(r, 800));
  await page.evaluate(async (yOrSel) => {
    document.querySelectorAll('.reveal, .reveal-stagger').forEach(el => el.classList.add('in'));
    if (typeof yOrSel === 'string' && yOrSel.startsWith('#')) {
      const el = document.querySelector(yOrSel);
      if (el) el.scrollIntoView({ block: 'center' });
    } else {
      window.scrollTo(0, parseInt(yOrSel, 10) || 0);
    }
  }, process.argv[3] && process.argv[3].startsWith('#') ? process.argv[3] : yArg);
  await new Promise(r => setTimeout(r, 500));
  const out = nextFilename();
  await page.screenshot({ path: out, fullPage: false });
  console.log('Saved:', out);
  await browser.close();
})();
