import puppeteer from 'puppeteer-core';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const url   = process.argv[2] || 'http://localhost:3000';
const label = process.argv[3] || 'mobile-full';
const lang  = process.argv[4];

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
  await page.setViewport({ width: 390, height: 844, deviceScaleFactor: 1, isMobile: true, hasTouch: true });
  if (lang) await page.evaluateOnNewDocument((l) => localStorage.setItem('ksat-lang', l), lang);
  await page.evaluateOnNewDocument(() => localStorage.setItem('ksat-consent','accepted'));
  await page.goto(url, { waitUntil: 'networkidle2', timeout: 30000 });
  await new Promise(r => setTimeout(r, 700));
  await page.evaluate(async () => {
    const total = document.documentElement.scrollHeight;
    const step = window.innerHeight * 0.5;
    for (let y = 0; y < total; y += step) { window.scrollTo(0, y); await new Promise(r => setTimeout(r, 70)); }
    window.scrollTo(0, 0);
    document.querySelectorAll('.reveal, .reveal-stagger').forEach(el => el.classList.add('in'));
  });
  await new Promise(r => setTimeout(r, 500));
  const out = nextFilename();
  await page.screenshot({ path: out, fullPage: true });
  console.log('Saved:', out);
  await browser.close();
})();
