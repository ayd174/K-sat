import puppeteer from 'puppeteer-core';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const url = process.argv[2] || 'http://localhost:3000';
const label = process.argv[3] || 'cookie';
const lang = process.argv[4];
const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const screenshotsDir = path.join(__dirname, 'temporary screenshots');
function next(){const files=fs.readdirSync(screenshotsDir).filter(f=>f.endsWith('.png'));let max=0;for(const f of files){const m=f.match(/^screenshot-(\d+)/);if(m)max=Math.max(max,parseInt(m[1]))}return path.join(screenshotsDir,`screenshot-${String(max+1).padStart(3,'0')}-${label}.png`)}
(async () => {
  const browser = await puppeteer.launch({ executablePath:CHROME, headless:true, args:['--no-sandbox']});
  const page = await browser.newPage();
  await page.setViewport({ width:1440, height:900 });
  if (lang) await page.evaluateOnNewDocument((l)=>localStorage.setItem('ksat-lang',l), lang);
  await page.goto(url, { waitUntil:'networkidle2'});
  await new Promise(r=>setTimeout(r,1800)); // wait for banner show timeout
  await page.evaluate(()=>document.querySelectorAll('.reveal,.reveal-stagger').forEach(el=>el.classList.add('in')));
  const out = next();
  await page.screenshot({ path: out, fullPage:false });
  console.log('Saved:', out);
  await browser.close();
})();
