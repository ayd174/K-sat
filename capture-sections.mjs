import puppeteer from 'puppeteer-core';
const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const browser = await puppeteer.launch({
  executablePath: CHROME, headless: true, args: ['--no-sandbox']
});
const page = await browser.newPage();
await page.setViewport({width:1440, height:900});
await page.goto('http://localhost:3000', {waitUntil:'networkidle2'});
await new Promise(r=>setTimeout(r,2000));

// Force English for clearest review
await page.evaluate(()=>{ localStorage.setItem('ksat_lang','en'); });
await page.reload({waitUntil:'networkidle2'});
await new Promise(r=>setTimeout(r,2000));

// Nav only (full width, 100px tall)
await page.screenshot({path:'temporary screenshots/check-nav.png', clip:{x:0,y:0,width:1440,height:100}});

// Hero (full viewport)
await page.screenshot({path:'temporary screenshots/check-hero.png', clip:{x:0,y:0,width:1440,height:900}});

// Services cards area
const svcsY = await page.evaluate(()=>document.getElementById('services').getBoundingClientRect().top + window.scrollY);
await page.evaluate((y)=>window.scrollTo(0,y), svcsY);
await new Promise(r=>setTimeout(r,400));
await page.screenshot({path:'temporary screenshots/check-services.png', clip:{x:0,y:0,width:1440,height:900}});

// Contact
const ctY = await page.evaluate(()=>document.getElementById('contact').getBoundingClientRect().top + window.scrollY);
await page.evaluate((y)=>window.scrollTo(0,y), ctY);
await new Promise(r=>setTimeout(r,400));
await page.screenshot({path:'temporary screenshots/check-contact.png', clip:{x:0,y:0,width:1440,height:900}});

// Footer
await page.evaluate(()=>window.scrollTo(0,document.body.scrollHeight));
await new Promise(r=>setTimeout(r,400));
const pgH = await page.evaluate(()=>document.body.scrollHeight);
const viewH = 400;
await page.screenshot({path:'temporary screenshots/check-footer.png', clip:{x:0, y:pgH-viewH, width:1440, height:viewH}});

await browser.close();
console.log('Sections captured. Page height:', pgH);
