// chatbot-plugin.js
class AITableChatbot {
  constructor(config) {
    this.apiEndpoint = config.apiEndpoint || 'http://localhost:5000';
    this.apiKey = config.apiKey || 'test_key_123';
    this.theme = config.theme || 'default';
    this.position = config.position || { bottom: 20, right: 20 };
    this.isMinimized = true;
    this.isOpen = false;
    this.isDraggingLauncher = false;

    this.init();
  }

  init() {
    this.createChatbotUI();
    this.applyStyles();
    document.body.appendChild(this.container);
    this.makeLauncherDraggable();
    this.makeDraggable();
    this.attachEventListeners();
    setTimeout(() => this.showWelcomeMessage(), 500);
  }

  createChatbotUI() {
    this.container = document.createElement('div');
    this.container.id = 'ai-table-chatbot';
    this.container.className = 'minimized';
    this.container.innerHTML = `
      <div class="chatbot-launcher" id="chatbot-launcher-drag">
        <div class="launcher-content">
          <div class="launcher-icon" style="font-size: 28px; font-weight: 800; color: white;">
            N
          </div>
          <div class="launcher-badge">1</div>
          <div class="launcher-pulse"></div>
        </div>
      </div>

      <div class="chatbot-window">
        <div class="chatbot-header" id="chatbot-drag-handle">
          <div class="chatbot-header-content">
            <div class="chatbot-avatar" style="font-size: 22px; font-weight: 800; color: white;">
              N
            </div>
            <div class="chatbot-title-section">
              <h3 class="chatbot-title">NexBot</h3>
              <p class="chatbot-status">
                <span class="status-dot"></span>
                Online • Ready to help
              </p>
            </div>
          </div>
          <div class="chatbot-controls">
            <button class="chatbot-refresh" type="button" title="Reset Chat">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"></path>
                <path d="M3 3v5h5"></path>
              </svg>
            </button>
            <button class="chatbot-close" type="button" title="Close">
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path d="M12 4L4 12M4 4L12 12" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
              </svg>
            </button>
          </div>
        </div>

        <div class="chatbot-messages">
          <div class="chatbot-welcome">
            <div class="welcome-icon">👋</div>
            <h4>Welcome! I'm NexBot</h4>
            <p>I can help you analyze your table data and provide insights. Try asking me:</p>
            <div class="suggestion-chips">
              
              
              <button class="suggestion-chip" data-message="Generate a dashboard from this data">
                📈 Generate dashboard
              </button>
              <button class="suggestion-chip" data-message="Give me key insights from the data">
                💡 Insights
              </button>
            </div>
            
          </div>
        </div>

        <div class="chatbot-typing-indicator" style="display: none;">
          <div class="typing-dot"></div>
          <div class="typing-dot"></div>
          <div class="typing-dot"></div>
          <span class="typing-text">AI is thinking...</span>
        </div>

        <div class="chatbot-input-area">
          
          <input type="text" placeholder="Type your question..." class="chatbot-input" />
          <button class="chatbot-send" type="button" title="Send message">
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none" class="send-icon">
              <path d="M18 2L9 11M18 2L12 18L9 11M18 2L2 8L9 11" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </button>
        </div>

        <div class="chatbot-footer">
          <span class="footer-text">Powered by AI • Secure & Private</span>
        </div>
      </div>
    `;
  }

  makeLauncherDraggable() {
    const launcher = this.container.querySelector('#chatbot-launcher-drag');
    let isDragging = false;
    let hasMoved = false;
    let startX = 0;
    let startY = 0;
    let initialX = 0;
    let initialY = 0;
    let currentX = 0;
    let currentY = 0;

    const onMouseDown = (e) => {
      isDragging = true;
      hasMoved = false;
      launcher.style.cursor = 'grabbing';

      const rect = launcher.getBoundingClientRect();
      startX = e.type.includes('touch') ? e.touches[0].clientX : e.clientX;
      startY = e.type.includes('touch') ? e.touches[0].clientY : e.clientY;
      initialX = rect.left;
      initialY = rect.top;
      e.preventDefault();
    };

    const onMouseMove = (e) => {
      if (!isDragging) return;
      e.preventDefault();
      hasMoved = true;

      const clientX = e.type.includes('touch') ? e.touches[0].clientX : e.clientX;
      const clientY = e.type.includes('touch') ? e.touches[0].clientY : e.clientY;
      currentX = initialX + (clientX - startX);
      currentY = initialY + (clientY - startY);

      launcher.style.position = 'fixed';
      launcher.style.left = currentX + 'px';
      launcher.style.top = currentY + 'px';
      launcher.style.bottom = 'auto';
      launcher.style.right = 'auto';
    };

    const onMouseUp = (e) => {
      if (!isDragging) return;
      isDragging = false;
      launcher.style.cursor = 'grab';
      this.launcherPosition = { x: currentX, y: currentY };

      if (hasMoved) {
        e.preventDefault();
        e.stopPropagation();
        setTimeout(() => { hasMoved = false; }, 100);
      }
    };

    launcher.addEventListener('mousedown', onMouseDown);
    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
    launcher.addEventListener('touchstart', onMouseDown, { passive: false });
    document.addEventListener('touchmove', onMouseMove, { passive: false });
    document.addEventListener('touchend', onMouseUp);

    this.launcherHasMoved = () => hasMoved;
  }

  makeDraggable() {
    const header = this.container.querySelector('#chatbot-drag-handle');
    const chatbotWindow = this.container.querySelector('.chatbot-window');
    let isDragging = false;
    let startX = 0;
    let startY = 0;
    let initialX = 0;
    let initialY = 0;
    let currentX = 0;
    let currentY = 0;

    const onMouseDown = (e) => {
      if (e.target.closest('.chatbot-controls')) return;
      isDragging = true;
      header.style.cursor = 'grabbing';

      const rect = chatbotWindow.getBoundingClientRect();
      startX = e.type.includes('touch') ? e.touches[0].clientX : e.clientX;
      startY = e.type.includes('touch') ? e.touches[0].clientY : e.clientY;
      initialX = rect.left;
      initialY = rect.top;
      e.preventDefault();
    };

    const onMouseMove = (e) => {
      if (!isDragging) return;
      e.preventDefault();

      const clientX = e.type.includes('touch') ? e.touches[0].clientX : e.clientX;
      const clientY = e.type.includes('touch') ? e.touches[0].clientY : e.clientY;
      currentX = initialX + (clientX - startX);
      currentY = initialY + (clientY - startY);

      chatbotWindow.style.left = currentX + 'px';
      chatbotWindow.style.top = currentY + 'px';
      chatbotWindow.style.bottom = 'auto';
      chatbotWindow.style.right = 'auto';
    };

    const onMouseUp = () => {
      if (!isDragging) return;
      isDragging = false;
      header.style.cursor = 'grab';
    };

    header.addEventListener('mousedown', onMouseDown);
    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
    header.addEventListener('touchstart', onMouseDown, { passive: false });
    document.addEventListener('touchmove', onMouseMove, { passive: false });
    document.addEventListener('touchend', onMouseUp);
  }

  applyStyles() {
    const style = document.createElement('style');
    style.textContent = `
      @keyframes slideInUp {
        from { opacity: 0; transform: translateY(20px); }
        to { opacity: 1; transform: translateY(0); }
      }
      @keyframes fadeIn {
        from { opacity: 0; }
        to { opacity: 1; }
      }
      @keyframes pulse {
        0%, 100% { transform: scale(1); opacity: 1; }
        50% { transform: scale(1.1); opacity: 0.8; }
      }
      @keyframes bounce {
        0%, 100% { transform: translateY(0); }
        50% { transform: translateY(-5px); }
      }
      @keyframes typing {
        0%, 60%, 100% { transform: translateY(0); }
        30% { transform: translateY(-10px); }
      }
      @keyframes blink {
        0%, 100% { opacity: 1; }
        50% { opacity: 0; }
      }
      .stream-cursor {
        display: inline-block;
        animation: blink 0.7s step-end infinite;
        color: oklch(0.7 0.15 220);
        font-weight: bold;
      }
      .message.bot code {
        background: #f1f5f9;
        padding: 2px 5px;
        border-radius: 4px;
        font-size: 12px;
        font-family: monospace;
      }

      #ai-table-chatbot {
        position: fixed;
        bottom: ${this.position.bottom}px;
        right: ${this.position.right}px;
        z-index: 9999;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      }

      .chatbot-launcher {
        position: fixed;
        bottom: ${this.position.bottom}px;
        right: ${this.position.right}px;
        width: 64px;
        height: 64px;
        background: oklch(0.7 0.15 220);
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        cursor: grab;
        box-shadow: 0 8px 24px oklch(0.7 0.15 220 / 0.4);
        transition: box-shadow 0.3s;
        animation: slideInUp 0.5s ease-out;
        z-index: 10000;
      }
      .chatbot-launcher:active { cursor: grabbing; }
      .chatbot-launcher:hover { box-shadow: 0 12px 32px oklch(0.7 0.15 220 / 0.5); }

      .launcher-content {
        position: relative;
        width: 100%;
        height: 100%;
        display: flex;
        align-items: center;
        justify-content: center;
        pointer-events: none;
      }
      .launcher-icon {
        position: relative;
        z-index: 2;
        animation: bounce 2s ease-in-out infinite;
      }
      .launcher-badge {
        position: absolute;
        top: -4px;
        right: -4px;
        background: #ff4757;
        color: white;
        width: 24px;
        height: 24px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 12px;
        font-weight: 600;
        border: 3px solid white;
        animation: pulse 2s ease-in-out infinite;
      }
      .launcher-pulse {
        position: absolute;
        width: 100%;
        height: 100%;
        border-radius: 50%;
        background: oklch(0.7 0.15 220);
        opacity: 0.6;
        animation: pulse 2s ease-in-out infinite;
      }

      .chatbot-window {
        position: fixed;
        bottom: 100px;
        right: 20px;
        width: 400px;
        height: 600px;
        background: white;
        border-radius: 20px;
        box-shadow: 0 12px 48px rgba(0, 0, 0, 0.15);
        display: none;
        flex-direction: column;
        overflow: hidden;
        animation: slideInUp 0.4s;
        z-index: 10000;
      }
      #ai-table-chatbot:not(.minimized) .chatbot-window { display: flex; }
      #ai-table-chatbot:not(.minimized) .chatbot-launcher { display: none; }

      .chatbot-header {
        background: oklch(0.7 0.15 220);
        color: white;
        padding: 20px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        cursor: grab;
        user-select: none;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
      }
      .chatbot-header:active { cursor: grabbing; }
      .chatbot-header-content {
        display: flex;
        align-items: center;
        gap: 12px;
        pointer-events: none;
      }
      .chatbot-avatar {
        width: 48px;
        height: 48px;
        background: rgba(255, 255, 255, 0.2);
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        backdrop-filter: blur(10px);
        border: 2px solid rgba(255, 255, 255, 0.3);
      }
      .chatbot-title-section {
        display: flex;
        flex-direction: column;
        gap: 4px;
      }
      .chatbot-title {
        margin: 0;
        font-size: 18px;
        font-weight: 600;
      }
      .chatbot-status {
        margin: 0;
        font-size: 13px;
        opacity: 0.9;
        display: flex;
        align-items: center;
        gap: 6px;
      }
      .status-dot {
        width: 8px;
        height: 8px;
        background: #4ade80;
        border-radius: 50%;
        animation: pulse 2s ease-in-out infinite;
      }
      .chatbot-controls {
        display: flex;
        gap: 8px;
        pointer-events: auto;
      }
      .chatbot-refresh, .chatbot-close {
        background: rgba(255, 255, 255, 0.2);
        color: white;
        border: none;
        width: 36px;
        height: 36px;
        border-radius: 10px;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: all 0.2s;
      }
      .chatbot-refresh:hover, .chatbot-close:hover {
        background: rgba(255, 255, 255, 0.3);
        transform: scale(1.05);
      }

      .chatbot-messages {
        flex: 1;
        overflow-y: auto;
        padding: 20px;
        background: linear-gradient(to bottom, #f8f9fa 0%, #ffffff 100%);
        display: flex;
        flex-direction: column;
        gap: 16px;
      }
      .chatbot-messages::-webkit-scrollbar { width: 6px; }
      .chatbot-messages::-webkit-scrollbar-thumb {
        background: #cbd5e0;
        border-radius: 3px;
      }

      .chatbot-welcome {
        text-align: center;
        padding: 20px;
        animation: fadeIn 0.6s;
      }
      .welcome-icon {
        font-size: 48px;
        margin-bottom: 16px;
        animation: bounce 1s;
      }
      .chatbot-welcome h4 {
        margin: 0 0 8px 0;
        font-size: 20px;
        color: #2d3748;
        font-weight: 600;
      }
      .chatbot-welcome p {
        margin: 0 0 20px 0;
        font-size: 14px;
        color: #718096;
      }

      .suggestion-chips {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        justify-content: center;
        margin-top: 16px;
      }
      .suggestion-chip {
        background: white;
        border: 2px solid #e2e8f0;
        color: #4a5568;
        padding: 10px 16px;
        border-radius: 20px;
        font-size: 13px;
        cursor: pointer;
        transition: all 0.2s;
        font-weight: 500;
      }
      .suggestion-chip:hover {
        background: oklch(0.7 0.15 220);
        color: white;
        border-color: transparent;
        transform: translateY(-2px);
        box-shadow: 0 4px 12px oklch(0.7 0.15 220 / 0.3);
      }

      .message {
        max-width: 80%;
        padding: 12px 16px;
        border-radius: 16px;
        word-wrap: break-word;
        font-size: 14px;
        animation: slideInUp 0.3s;
        position: relative;
      }
      .message.user {
        background: oklch(0.7 0.15 220);
        color: white;
        margin-left: auto;
        border-bottom-right-radius: 4px;
        box-shadow: 0 4px 12px oklch(0.7 0.15 220 / 0.3);
      }
      .message.bot {
        background: white;
        color: #2d3748;
        border: 1px solid #e2e8f0;
        border-bottom-left-radius: 4px;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
        padding-left: 44px;
      }
      .message.bot::before {
        content: 'N';
        font-weight: 800;
        color: oklch(0.7 0.15 220);
        position: absolute;
        left: 12px;
        top: 12px;
        font-size: 20px;
      }

      .chatbot-typing-indicator {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 12px 20px;
        background: white;
        border-top: 1px solid #e2e8f0;
      }
      .typing-dot {
        width: 8px;
        height: 8px;
        background: oklch(0.7 0.15 220);
        border-radius: 50%;
        animation: typing 1.4s ease-in-out infinite;
      }
      .typing-dot:nth-child(2) { animation-delay: 0.2s; }
      .typing-dot:nth-child(3) { animation-delay: 0.4s; }
      .typing-text {
        font-size: 13px;
        color: #718096;
        font-style: italic;
      }

      .chatbot-input-area {
        display: flex;
        padding: 16px 20px;
        gap: 12px;
        background: white;
        border-top: 1px solid #e2e8f0;
        align-items: center;
      }
      .chatbot-attach {
        background: transparent;
        border: none;
        color: #718096;
        width: 40px;
        height: 40px;
        border-radius: 10px;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: all 0.2s;
      }
      .chatbot-attach:hover {
        background: #f7fafc;
        color: oklch(0.7 0.15 220);
      }
      .chatbot-input {
        flex: 1;
        padding: 12px 16px;
        border: 2px solid #e2e8f0;
        border-radius: 12px;
        outline: none;
        font-size: 14px;
        background: #f7fafc;
      }
      .chatbot-input:focus {
        border-color: oklch(0.7 0.15 220);
        background: white;
        box-shadow: 0 0 0 3px oklch(0.7 0.15 220 / 0.1);
      }
      .chatbot-send {
        background: oklch(0.7 0.15 220);
        color: white;
        border: none;
        width: 44px;
        height: 44px;
        border-radius: 12px;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: all 0.2s;
        box-shadow: 0 4px 12px oklch(0.7 0.15 220 / 0.3);
      }
      .chatbot-send:hover:not(:disabled) {
        transform: scale(1.05);
      }
      .chatbot-send:disabled {
        opacity: 0.5;
        cursor: not-allowed;
      }

      .chatbot-footer {
        padding: 12px 20px;
        background: #f7fafc;
        border-top: 1px solid #e2e8f0;
        text-align: center;
      }
      .footer-text {
        font-size: 12px;
        color: #a0aec0;
      }
    `;
    document.head.appendChild(style);
  }

  showWelcomeMessage() {
    const badge = this.container.querySelector('.launcher-badge');
    if (badge) {
      setTimeout(() => {
        badge.style.animation = 'pulse 0.5s ease-in-out 3';
      }, 1000);
    }
  }

  async sendMessage(message) {
    // Detect dashboard intent — use non-streaming endpoint for full HTML
    const dashKeywords = ['dashboard', 'chart', 'graph', 'visuali', 'plot'];
    const isDashboard  = dashKeywords.some(k => message.toLowerCase().includes(k));
    if (isDashboard) {
      return await this.generateDashboard(message, 'inbuilt');
    }

    // For regular Q&A use the streaming endpoint
    return new Promise((resolve) => {
      const body = { message };
      if (this.activeSourceId) body.data_source_id = this.activeSourceId;

      // Create the bot message bubble immediately so tokens stream into it
      const messagesContainer = this.container.querySelector('.chatbot-messages');
      const msgDiv = document.createElement('div');
      msgDiv.className = 'message bot streaming';
      msgDiv.innerHTML = '<span class="stream-cursor">▍</span>';
      messagesContainer.appendChild(msgDiv);
      messagesContainer.scrollTop = messagesContainer.scrollHeight;

      let fullText = '';

      fetch(`${this.apiEndpoint}/api/v1/analyze/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${this.apiKey}` },
        body: JSON.stringify(body)
      }).then(resp => {
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        const read = () => {
          reader.read().then(({ done, value }) => {
            if (done) {
              // Finalise bubble
              msgDiv.classList.remove('streaming');
              const cursor = msgDiv.querySelector('.stream-cursor');
              if (cursor) cursor.remove();
              resolve({ success: true, streamed: true });
              return;
            }
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop(); // keep incomplete line

            for (const line of lines) {
              if (!line.startsWith('data: ')) continue;
              try {
                const evt = JSON.parse(line.slice(6));
                if (evt.error) {
                  msgDiv.innerHTML = `❌ ${evt.error}`;
                  resolve({ success: false, streamed: true });
                  return;
                }
                if (evt.token) {
                  fullText += evt.token;
                  // Render markdown-lite inline
                  const cursor = msgDiv.querySelector('.stream-cursor');
                  const rendered = fullText
                    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
                    .replace(/\*\*(.*?)\*\*/g,'<strong>$1</strong>')
                    .replace(/`(.*?)`/g,'<code>$1</code>')
                    .replace(/\n/g,'<br>');
                  msgDiv.innerHTML = rendered + '<span class="stream-cursor">▍</span>';
                  messagesContainer.scrollTop = messagesContainer.scrollHeight;
                }
              } catch (_) {}
            }
            read();
          });
        };
        read();
      }).catch(err => {
        msgDiv.innerHTML = `❌ ${err.message}`;
        resolve({ success: false, streamed: true });
      });
    });
  }

  async uploadFile(file) {
    const formData = new FormData();
    formData.append('file', file);
    try {
      const resp = await fetch(`${this.apiEndpoint}/api/v1/data/upload-file`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${this.apiKey}` },
        body: formData
      });
      const data = await resp.json();
      if (data.success) {
        this.activeSourceId = data.source_id;
        this.displayMessage(
          `✅ Uploaded **${data.filename}** — ${data.record_count} rows loaded. You can now ask questions about this data!`,
          'bot'
        );
      } else {
        this.displayMessage(`❌ Upload failed: ${data.error}`, 'bot');
      }
    } catch (e) {
      this.displayMessage(`❌ Upload error: ${e.message}`, 'bot');
    }
  }

  async generateDashboard(message, mode) {
    try {
      const body = { message, type: mode };
      if (this.activeSourceId) body.data_source_id = this.activeSourceId;
      const resp = await fetch(`${this.apiEndpoint}/api/v1/dashboard/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${this.apiKey}` },
        body: JSON.stringify(body)
      });
      const data = await resp.json();
      if (!data.success) return { success: false, insight: data.error || 'Dashboard generation failed.' };
      if (mode === 'download') {
        return { success: true, insight: `📥 Dashboard ready! [Download here](${this.apiEndpoint}${data.download_url})`, downloadUrl: `${this.apiEndpoint}${data.download_url}` };
      }
      return { success: true, dashboard: data.html, downloadUrl: `${this.apiEndpoint}${data.download_url}` };
    } catch (e) {
      return { success: false, insight: `Dashboard error: ${e.message}` };
    }
  }

  attachEventListeners() {
    const input = this.container.querySelector('.chatbot-input');
    const sendBtn = this.container.querySelector('.chatbot-send');
    const refreshBtn = this.container.querySelector('.chatbot-refresh');
    const closeBtn = this.container.querySelector('.chatbot-close');
    const launcher = this.container.querySelector('.chatbot-launcher');
    const attachBtn = this.container.querySelector('.chatbot-attach');
    const fileInput = this.container.querySelector('#chatbot-file-input');
    const suggestionChips = this.container.querySelectorAll('.suggestion-chip');

    launcher.addEventListener('click', (e) => {
      if (!this.launcherHasMoved || !this.launcherHasMoved()) this.toggleWindow();
    });

    sendBtn.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); this.handleSend(input.value); });
    input.addEventListener('keypress', (e) => { if (e.key === 'Enter') { e.preventDefault(); this.handleSend(input.value); } });
    refreshBtn.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); this.resetChat(); });
    closeBtn.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); this.toggleWindow(); });

    // File upload via attach button
    if (attachBtn && fileInput) {
      attachBtn.addEventListener('click', () => fileInput.click());
      fileInput.addEventListener('change', async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        const welcomeMsg = this.container.querySelector('.chatbot-welcome');
        if (welcomeMsg) welcomeMsg.style.display = 'none';
        this.displayMessage(`📎 Uploading ${file.name}…`, 'user');
        const typingIndicator = this.container.querySelector('.chatbot-typing-indicator');
        typingIndicator.style.display = 'flex';
        await this.uploadFile(file);
        typingIndicator.style.display = 'none';
        fileInput.value = '';
      });
    }

    suggestionChips.forEach(chip => {
      chip.addEventListener('click', (e) => {
        e.preventDefault();
        const action = chip.getAttribute('data-action');
        const message = chip.getAttribute('data-message');
        if (action === 'upload' && fileInput) { fileInput.click(); return; }
        if (action === 'connect') {
          input.value = '';
          input.placeholder = 'Enter: sqlite:///path/to/db.sqlite | SELECT * FROM table';
          input.focus();
          this.displayMessage('To connect a database, type your query in the format:\n`sqlite:///path/to/db.sqlite | SELECT * FROM table`\nThen press Enter.', 'bot');
          return;
        }
        if (message) { input.value = message; this.handleSend(message); }
      });
    });
  }

  resetChat() {
    this.activeSourceId = null;
    const messages = this.container.querySelectorAll('.message');
    messages.forEach(m => m.remove());
    
    const welcomeMsg = this.container.querySelector('.chatbot-welcome');
    if (welcomeMsg) welcomeMsg.style.display = 'block';
    
    const typingInd = this.container.querySelector('.chatbot-typing-indicator');
    if (typingInd) typingInd.style.display = 'none';
    
    const input = this.container.querySelector('.chatbot-input');
    if (input) {
      input.value = '';
      input.placeholder = 'Type your question...';
    }
  }

  toggleWindow() {
    this.container.classList.toggle('minimized');
    this.isOpen = !this.isOpen;

    if (this.isOpen) {
      setTimeout(() => {
        const input = this.container.querySelector('.chatbot-input');
        input.focus();
      }, 100);

      const badge = this.container.querySelector('.launcher-badge');
      if (badge) {
        badge.style.display = 'none';
      }
    }
  }

  async handleSend(message) {
    if (!message.trim()) return;

    // Handle DB connect shorthand: "connStr | SELECT ..."
    if (message.includes(' | ')) {
      const [connStr, query] = message.split(' | ');
      const dbType = connStr.startsWith('sqlite') ? 'sqlite' : connStr.startsWith('postgres') ? 'postgres' : 'mysql';
      const welcomeMsg = this.container.querySelector('.chatbot-welcome');
      if (welcomeMsg) welcomeMsg.style.display = 'none';
      const input = this.container.querySelector('.chatbot-input');
      const sendBtn = this.container.querySelector('.chatbot-send');
      const typingIndicator = this.container.querySelector('.chatbot-typing-indicator');
      this.displayMessage(message, 'user');
      input.value = ''; input.disabled = true; sendBtn.disabled = true;
      typingIndicator.style.display = 'flex';
      try {
        const resp = await fetch(`${this.apiEndpoint}/api/v1/data/connect-db`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${this.apiKey}` },
          body: JSON.stringify({ type: dbType, connection_string: connStr.trim(), query: query.trim() })
        });
        const data = await resp.json();
        typingIndicator.style.display = 'none';
        if (data.success) {
          this.activeSourceId = data.source_id;
          this.displayMessage(`✅ Connected! ${data.record_count} rows loaded. Ask me anything about the data.`, 'bot');
        } else {
          this.displayMessage(`❌ DB error: ${data.error}`, 'bot');
        }
      } catch(e) { typingIndicator.style.display = 'none'; this.displayMessage(`❌ ${e.message}`, 'bot'); }
      finally { input.disabled = false; sendBtn.disabled = false; input.placeholder = 'Type your question...'; input.focus(); }
      return;
    }

    const input = this.container.querySelector('.chatbot-input');
    const sendBtn = this.container.querySelector('.chatbot-send');
    const typingIndicator = this.container.querySelector('.chatbot-typing-indicator');
    const welcomeMsg = this.container.querySelector('.chatbot-welcome');
    if (welcomeMsg) welcomeMsg.style.display = 'none';
    input.disabled = true; sendBtn.disabled = true;
    this.displayMessage(message, 'user');
    input.value = '';
    typingIndicator.style.display = 'flex';

    try {
      const response = await this.sendMessage(message);
      typingIndicator.style.display = 'none';
      // Streamed responses already inserted their own bubble — skip displayMessage
      if (!response.streamed) {
        if (response.dashboard) {
          this.displayDashboard(response.dashboard, response.downloadUrl);
        } else if (response.downloadUrl) {
          this.displayMessage(response.insight || 'Dashboard ready!', 'bot');
          window.open(response.downloadUrl, '_blank');
        } else {
          this.displayMessage(response.insight || 'No response', 'bot');
        }
      }
    } catch (error) {
      typingIndicator.style.display = 'none';
      this.displayMessage('Error occurred. Please try again.', 'bot');
    } finally {
      input.disabled = false; sendBtn.disabled = false; input.focus();
    }
  }

  displayDashboard(html, downloadUrl) {
    const messagesContainer = this.container.querySelector('.chatbot-messages');
    const wrapper = document.createElement('div');
    wrapper.className = 'message bot dashboard-message';
    wrapper.style.cssText = 'max-width:100%;padding:12px;border-radius:12px;background:white;border:1px solid #e2e8f0;margin-bottom:12px;';
    
    const textMsg = document.createElement('p');
    textMsg.textContent = '📈 Your dashboard has been generated successfully! Download the standalone HTML file below to view it.';
    textMsg.style.cssText = 'margin: 0 0 12px 0; font-size: 14px; color: #2d3748;';
    
    // Direct link to the HTML file generated by the backend
    const dlBtn = document.createElement('a');
    dlBtn.textContent = '⬇️ Download Dashboard File';
    dlBtn.href = downloadUrl;
    dlBtn.download = 'dashboard.html';
    dlBtn.target = '_blank';
    dlBtn.style.cssText = 'display:block;width:100%;padding:10px;background:linear-gradient(135deg,oklch(0.7 0.15 220),#764ba2);color:#fff;border:none;border-radius:8px;cursor:pointer;font-size:14px;font-weight:bold;text-align:center;text-decoration:none;box-sizing:border-box;box-shadow:0 4px 6px rgba(102,126,234,0.2);';

    wrapper.appendChild(textMsg);
    wrapper.appendChild(dlBtn);
    messagesContainer.appendChild(wrapper);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
  }

  displayMessage(text, sender) {
    const messagesContainer = this.container.querySelector('.chatbot-messages');
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${sender}`;
    // Render simple markdown bold (**text**) and newlines
    messageDiv.innerHTML = text
      .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
      .replace(/\*\*(.*?)\*\*/g,'<strong>$1</strong>')
      .replace(/`(.*?)`/g,'<code>$1</code>')
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g,'<a href="$2" target="_blank" style="color:oklch(0.7 0.15 220)">$1</a>')
      .replace(/\n/g,'<br>');
    messagesContainer.appendChild(messageDiv);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
  }

  destroy() {
    if (this.container && this.container.parentNode) {
      this.container.remove();
    }
  }
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = AITableChatbot;
} else {
  window.AITableChatbot = AITableChatbot;
}

console.log('✅ AI Table Chatbot loaded successfully!');