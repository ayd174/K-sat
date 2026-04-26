import puppeteer from 'puppeteer-core';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const url   = process.argv[2] || 'http://localhost:3000';
const yArg  = process.argv[3] || '0';
const label = process.argv[4] || 'mobile';
const lang  = process.argv[5];

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const screenshotsDir = path.join(__dirname, 'temporary screenshots');

function nextFilename() {
  const files = fs.readdirSync(screenshotsDir).filter(f => f.endsWith('.png'));
  let max = 0;
  for (const f of files) { const m = f.match(/^screenshot-(\d+)/); if (m) max = Math.max(max, parseInt(m[1])); }
  return path.join(screenshotsDir, `screenshot-${String(max+1).padStart(3,'0')}-${label}.png`);
}

(async () => {
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: true, args: ['--no-sandbox'] });
  const page = await browser.newPage();
  await page.setViewport({ width: 390, height: 844, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  if (lang) await page.evaluateOnNewDocument((l) => localStorage.setItem('ksat-lang', l), lang);
  // Pre-mark cookie consent so banner doesn't cover content
  await page.evaluateOnNewDocument(() => localStorage.setItem('ksat-consent','accepted'));
  await page.goto(url, { waitUntil: 'networkidle2', timeout: 30000 });
  await new Promise(r => setTimeout(r, 700));
  await page.evaluate(async (y) => {
    document.querySelectorAll('.reveal, .reveal-stagger').forEach(el => el.classList.add('in'));
    if (typeof y === 'string' && y.startsWith('#')) {
      const el = document.querySelector(y);
      if (el) {
        const rect = el.getBoundingClientRect();
        window.scrollTo(0, rect.top + window.scrollY - 80);
      }
    } else {
      window.scrollTo(0, parseInt(y, 10) || 0);
    }
  }, yArg);
  await new Promise(r => setTimeout(r, 400));
  const out = nextFilename();
  await page.screenshot({ path: out, fullPage: false });
  console.log('Saved:', out);
  await browser.close();
})();
