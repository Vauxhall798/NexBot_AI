const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  page.on('console', msg => console.log('PAGE LOG:', msg.text()));
  page.on('pageerror', err => console.log('PAGE ERROR:', err.message));
  await page.goto('file:///Users/vishaalarun/PycharmProjects/Chatbot_AI_Project/downloads/dashboard_09f2b5a2.html');
  await browser.close();
})();
