const { chromium } = require('playwright');
const path = require('path');
(async () => {
  const [,, input, output, label] = process.argv;
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto('file://' + path.resolve(input), { waitUntil: 'networkidle' });
  const broken = await page.$$eval('img', imgs => imgs.filter(i => !i.complete || i.naturalWidth === 0).map(i => i.src));
  if (broken.length) { console.error('IMAGENS_QUEBRADAS', broken); process.exit(2); }
  await page.pdf({ path: output, format: 'A4', printBackground: true, preferCSSPageSize: true,
    displayHeaderFooter: true,
    headerTemplate: '<div></div>',
    footerTemplate: `<div style="font-family:DejaVu Sans,sans-serif;font-size:7pt;color:#666;width:100%;padding:0 18mm;display:flex;justify-content:space-between"><span>${label}</span><span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>` });
  console.log('ok', output, 'chromium', browser.version());
  await browser.close();
})();
