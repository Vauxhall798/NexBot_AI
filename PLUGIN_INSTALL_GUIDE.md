# 🤖 NexBot AI — Add This Chatbot to Your Website

> **NexBot AI** is an AI-powered data analyst chatbot widget. Drop it into any website with just **2 steps** — no coding experience needed.

**Server URL:** `https://nexbot-ai-lb0h.onrender.com`

---

## Step 1: Get Your API Key (One-Time Setup)

You need a **registration password** from the NexBot administrator to get started.

### Option A — Using Terminal / Command Prompt

**Mac/Linux:**
```bash
curl -X POST https://nexbot-ai-lb0h.onrender.com/api/v1/register \
  -H "Content-Type: application/json" \
  -d '{
    "password": "PASSWORD_FROM_ADMIN",
    "name": "Your Name",
    "email": "your@email.com"
  }'
```

**Windows (PowerShell):**
```powershell
Invoke-RestMethod -Uri "https://nexbot-ai-lb0h.onrender.com/api/v1/register" `
  -Method POST -ContentType "application/json" `
  -Body '{"password":"PASSWORD_FROM_ADMIN","name":"Your Name","email":"your@email.com"}'
```

### Option B — Using Postman / Thunder Client

1. Open Postman → New Request
2. Set method to **POST**
3. URL: `https://nexbot-ai-lb0h.onrender.com/api/v1/register`
4. Go to **Body** → select **raw** → choose **JSON**
5. Paste:
```json
{
  "password": "PASSWORD_FROM_ADMIN",
  "name": "Your Name",
  "email": "your@email.com"
}
```
6. Click **Send**

### Option C — Using Your Browser Console

Open any webpage → press `F12` → go to **Console** tab → paste:

```javascript
fetch('https://nexbot-ai-lb0h.onrender.com/api/v1/register', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    password: 'PASSWORD_FROM_ADMIN',
    name: 'Your Name',
    email: 'your@email.com'
  })
}).then(r => r.json()).then(d => console.log(d));
```

### What You'll Get Back

```json
{
  "success": true,
  "api_key": "nxb_8b87c4eddffd402aa7e2c4e324c5f476",
  "plan": "free",
  "query_limit": 100,
  "embed_snippet": "<!-- NexBot AI Plugin -->...",
  "message": "Plugin registered. Paste the embed_snippet into your HTML."
}
```

> ⚡ **Save your `api_key`** — you'll need it in the next step.

---

## Step 2: Add the Chatbot to Your Website

Copy the code below and paste it into your website's HTML **before the closing `</body>` tag**.

**Replace `YOUR_API_KEY` with the key you received in Step 1.**

```html
<!-- 🤖 NexBot AI Chatbot Widget -->
<script src="https://nexbot-ai-lb0h.onrender.com/plugin/chatbot-plugin.js"></script>
<script>
  document.addEventListener('DOMContentLoaded', function() {
    new AITableChatbot({
      apiEndpoint: 'https://nexbot-ai-lb0h.onrender.com',
      apiKey: 'YOUR_API_KEY'
    });
  });
</script>
```

**That's it!** A chat bubble (🤖) will appear in the bottom-right corner of your website.

---

## Platform-Specific Instructions

### 📄 Plain HTML Website
```html
<!DOCTYPE html>
<html>
<head>
    <title>My Website</title>
</head>
<body>
    <h1>My Website</h1>
    <p>Your content here...</p>

    <!-- Paste NexBot right before </body> -->
    <script src="https://nexbot-ai-lb0h.onrender.com/plugin/chatbot-plugin.js"></script>
    <script>
      document.addEventListener('DOMContentLoaded', function() {
        new AITableChatbot({
          apiEndpoint: 'https://nexbot-ai-lb0h.onrender.com',
          apiKey: 'YOUR_API_KEY'
        });
      });
    </script>
</body>
</html>
```

### 🟦 WordPress
1. Install the **"Insert Headers and Footers"** plugin (or use **Appearance → Theme File Editor**)
2. Go to **Settings → Insert Headers and Footers**
3. In the **"Scripts in Footer"** box, paste:
```html
<script src="https://nexbot-ai-lb0h.onrender.com/plugin/chatbot-plugin.js"></script>
<script>
  document.addEventListener('DOMContentLoaded', function() {
    new AITableChatbot({
      apiEndpoint: 'https://nexbot-ai-lb0h.onrender.com',
      apiKey: 'YOUR_API_KEY'
    });
  });
</script>
```
4. Click **Save**

### ⚛️ React / Next.js
Create a component:
```jsx
// components/NexBot.jsx
'use client';
import { useEffect } from 'react';

export default function NexBot() {
  useEffect(() => {
    const script = document.createElement('script');
    script.src = 'https://nexbot-ai-lb0h.onrender.com/plugin/chatbot-plugin.js';
    script.onload = () => {
      new window.AITableChatbot({
        apiEndpoint: 'https://nexbot-ai-lb0h.onrender.com',
        apiKey: 'YOUR_API_KEY'
      });
    };
    document.body.appendChild(script);
  }, []);
  return null;
}
```
Then add `<NexBot />` to your layout or page.

### 💚 Vue.js
```vue
<script setup>
import { onMounted } from 'vue'

onMounted(() => {
  const s = document.createElement('script')
  s.src = 'https://nexbot-ai-lb0h.onrender.com/plugin/chatbot-plugin.js'
  s.onload = () => {
    new window.AITableChatbot({
      apiEndpoint: 'https://nexbot-ai-lb0h.onrender.com',
      apiKey: 'YOUR_API_KEY'
    })
  }
  document.body.appendChild(s)
})
</script>
```

### 🛍️ Shopify
1. Go to **Online Store → Themes → Edit Code**
2. Open `theme.liquid`
3. Paste the script block just before `</body>`
4. Save

### 📐 Wix
1. Go to **Settings → Custom Code**
2. Click **+ Add Custom Code**
3. Paste the script block
4. Set placement to **Body - End**
5. Apply to **All Pages** → Save

### 🟨 Squarespace
1. Go to **Settings → Advanced → Code Injection**
2. In the **Footer** section, paste the script block
3. Save

---

## What Can Users Do With the Chatbot?

| Feature | How | Example |
|---------|-----|---------|
| 💬 **Ask Questions** | Type in the chat box | *"What are the top products?"* |
| 📊 **Generate Dashboards** | Ask for charts | *"Create a sales dashboard"* |
| 📎 **Upload Data** | Click attach (📎) button | Upload CSV or Excel files |
| 💡 **Get Insights** | Click suggestion chips | *"Give me key insights"* |

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Chat bubble doesn't appear | Check browser console (F12) for errors. Verify your API key is correct. |
| "Invalid API key" | Re-register or check you copied the full key. |
| First load is slow (~30s) | Normal — free Render servers sleep after 15 min of inactivity. |
| CORS error | The server allows all origins. Clear browser cache and retry. |

---

## Need Help?

Visit this URL in your browser for live setup instructions:
**https://nexbot-ai-lb0h.onrender.com/api/v1/plugin/embed**
