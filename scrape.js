const { chromium } = require('playwright');
const fs = require('fs');

const companies = [
  'microsoft',
  'google',
  'amazon',
];

(async () => {
  const browser = await chromium.launch({ headless: false });
  const page = await browser.newPage();

  // LOGIN
  await page.goto('https://www.linkedin.com/login');
  await page.waitForTimeout(2000);
  await page.fill('#username', 'testacc20262020@gmail.com');
  await page.fill('#password', 'testaccount2026');
  await page.click('button[type="submit"]');

  console.log('⏳ Complete OTP if asked...');
  await page.waitForURL('**/feed/**', { timeout: 60000 });
  console.log('✅ Logged in!\n');

  const results = [];

  for (const company of companies) {
    console.log(`\n🔍 Scraping: ${company}...`);

    try {
      // ── MAIN PAGE ──
      await page.goto(`https://www.linkedin.com/company/${company}/`);
      await page.waitForTimeout(4000);

      // Close popup if appears
      try {
        await page.locator('button[aria-label="Dismiss"]').click({ timeout: 3000 });
      } catch {}

      // Company name
      let name = '';
      try { name = await page.locator('h1').first().innerText({ timeout: 5000 }); } catch {}

      // Followers — look for "X followers" text on page
      let followers = '';
      try {
        const bodyText = await page.locator('body').innerText();
        const match = bodyText.match(/([\d,\.]+[KkMm]?\s*followers)/i);
        if (match) followers = match[1];
      } catch {}

      // Employees — look for "X employees" text
      let employees = '';
      try {
        const bodyText = await page.locator('body').innerText();
        const match = bodyText.match(/([\d,]+\+?\s*employees)/i);
        if (match) employees = match[1];
      } catch {}

      // ── ABOUT PAGE ──
      await page.goto(`https://www.linkedin.com/company/${company}/about/`);
      await page.waitForTimeout(3000);

      let industry = '';
      let location = '';
      let website = '';
      let description = '';
      let size = '';

      try {
        const aboutText = await page.locator('body').innerText();

        // Website
        const webMatch = aboutText.match(/Website\n(.+)/);
        if (webMatch) website = webMatch[1].trim();

        // Industry
        const indMatch = aboutText.match(/Industry\n(.+)/);
        if (indMatch) industry = indMatch[1].trim();

        // Company size
        const sizeMatch = aboutText.match(/Company size\n(.+)/);
        if (sizeMatch) size = sizeMatch[1].trim();

        // Headquarters
        const hqMatch = aboutText.match(/Headquarters\n(.+)/);
        if (hqMatch) location = hqMatch[1].trim();
      } catch {}

      // Description
      try {
        description = await page.locator('p.break-words').first().innerText({ timeout: 5000 });
        description = description.substring(0, 300).replace(/\n/g, ' ');
      } catch {}

      // ── JOBS PAGE ──
      let jobCount = 'N/A';
      try {
        await page.goto(`https://www.linkedin.com/company/${company}/jobs/`);
        await page.waitForTimeout(3000);
        const bodyText = await page.locator('body').innerText();
        const jobMatch = bodyText.match(/([\d,]+)\s*job/i);
        if (jobMatch) jobCount = jobMatch[1] + ' jobs';
      } catch {}

      const data = {
        Company:     name.trim(),
        Followers:   followers || 'N/A',
        Employees:   employees || size || 'N/A',
        Industry:    industry || 'N/A',
        Location:    location || 'N/A',
        Website:     website || 'N/A',
        Open_Jobs:   jobCount,
        Description: description || 'N/A',
      };

      results.push(data);
      console.log('✅ Scraped:', data.Company);
      console.log('   Followers:', data.Followers);
      console.log('   Employees:', data.Employees);
      console.log('   Jobs:', data.Open_Jobs);

    } catch (err) {
      console.log(`❌ Error with ${company}:`, err.message);
    }

    await page.waitForTimeout(3000);
  }

  // SAVE TO CSV
  if (results.length > 0) {
    const headers = Object.keys(results[0]).join(',');
    const rows = results.map(r =>
      Object.values(r)
        .map(v => `"${String(v).replace(/"/g, "'")}"`)
        .join(',')
    );
    const csv = [headers, ...rows].join('\n');
    fs.writeFileSync('companies.csv', csv, 'utf8');
    console.log('\n🎉 ALL DONE! Saved to companies.csv');
    console.log(`📊 Total companies scraped: ${results.length}`);
  }

  await browser.close();
})();