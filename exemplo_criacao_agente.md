<div class="container-sm form-page fade-up">
  <div class="section-label">New Agent</div>
  <h1>Create a New Agent</h1>
  <p class="form-sub">Configure your AI agent in 6 steps</p>

  

  <div class="steps">
    <div class="step done" data-step="1"><span class="step-num">1</span><span class="step-text"> Name &amp; Personality</span></div>
    <div class="step done" data-step="2"><span class="step-num">2</span><span class="step-text"> Channel</span></div>
    <div class="step" data-step="3"><span class="step-num">3</span><span class="step-text"> Guardrails</span></div>
    <div class="step" data-step="4"><span class="step-num">4</span><span class="step-text"> Voice Agent</span></div>
    <div class="step" data-step="5"><span class="step-num">5</span><span class="step-text"> API Connectors</span></div>
    <div class="step" data-step="6"><span class="step-num">6</span><span class="step-text"> Review &amp; Deploy</span></div>
  </div>

  <form method="POST" action="/agents" id="agent-form" novalidate="">
    <!-- Hidden template_type field — populated by JS when a template is selected -->
    <input type="hidden" name="template_type" id="template_type_field" value="">

    <!-- ── Template Picker (above step 1) ──────────────────────────── -->
    <div class="template-picker" id="template-picker">
      <div class="template-picker-label">⚡ Start from a template — or build from scratch</div>
      <div class="template-grid">
        
        <!-- Custom Agent (no template) -->
        <div class="template-card" data-template="" id="tpl-custom">
          <div class="template-card-icon">⚙️</div>
          <div class="template-card-body">
            <h4>Custom Agent</h4>
            <p>Build from scratch. Write your own instructions, personality, and connect to any external API.</p>
          </div>
        </div>
      </div>
      <div class="template-active-banner" id="template-active-banner">
        <span id="template-active-text">✅ DfE Education template applied — instructions pre-filled</span>
        <a onclick="clearTemplate()">Clear template</a>
      </div>
    </div>

    <!-- Step 1: Name & Personality -->
    <div class="form-section" data-step="1">
      <div class="form-group">
        <label for="name">Agent Name *</label>
        <input type="text" id="name" name="name" placeholder="e.g. Customer Support Bot" required="">
        <div class="hint">A friendly name for your agent</div>
      </div>
      <div class="form-group">
        <label for="personality">Personality</label>
        <textarea id="personality" name="personality" placeholder="e.g. Friendly and professional. Responds in a helpful tone. Uses emojis occasionally." rows="3"></textarea>
        <div class="hint">Describe how your agent should communicate</div>
      </div>
      <div class="form-group">
        <label for="instructions">Instructions</label>
        <textarea id="instructions" name="instructions" placeholder="e.g. Answer questions about our SaaS product. If a customer wants to cancel, offer a 20% discount first. Escalate billing issues to the team." rows="5"></textarea>
        <div class="hint">Tell your agent what to do and how to handle different situations</div>
      </div>
      <div class="form-nav">
        <div></div>
        <button type="button" class="btn btn-primary" data-action="goStep" data-arg="2">Next: Choose Channel →</button>
      </div>
    </div>

    <!-- Step 2: Channel -->
    <div class="form-section" data-step="2">
      <div class="form-group">
        <label>Select Channel *</label>
        <div class="channel-grid">
          <label class="channel-option">
            <input type="radio" name="channel" value="telegram" required="">
            <div class="channel-label">
              <span class="channel-emoji">✈️</span>
              <div class="channel-info">
                <h4>Telegram</h4>
                <p>Bot API token required</p>
              </div>
            </div>
          </label>
          <label class="channel-option">
            <input type="radio" name="channel" value="whatsapp">
            <div class="channel-label">
              <span class="channel-emoji">💬</span>
              <div class="channel-info">
                <h4>WhatsApp</h4>
                <p>Business API credentials</p>
              </div>
            </div>
          </label>
          <label class="channel-option">
            <input type="radio" name="channel" value="discord">
            <div class="channel-label">
              <span class="channel-emoji">🎮</span>
              <div class="channel-info">
                <h4>Discord</h4>
                <p>Bot token + server ID</p>
              </div>
            </div>
          </label>
          <label class="channel-option">
            <input type="radio" name="channel" value="slack">
            <div class="channel-label">
              <span class="channel-emoji">💼</span>
              <div class="channel-info">
                <h4>Slack</h4>
                <p>One-click OAuth setup</p>
              </div>
            </div>
          </label>
          <label class="channel-option">
            <input type="radio" name="channel" value="email">
            <div class="channel-label">
              <span class="channel-emoji">📧</span>
              <div class="channel-info">
                <h4>Email</h4>
                <p>IMAP/SMTP credentials</p>
              </div>
            </div>
          </label>
          <label class="channel-option">
            <input type="radio" name="channel" value="webchat">
            <div class="channel-label">
              <span class="channel-emoji">🌐</span>
              <div class="channel-info">
                <h4>Web Chat</h4>
                <p>Embed on any website</p>
              </div>
            </div>
          </label>
        </div>
      </div>

      <div class="credentials-fields hidden" id="creds-telegram">
        <div class="form-group">
          <label for="channel_token_telegram">Telegram Bot Token</label>
          <input type="text" id="channel_token_telegram" placeholder="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11">
          <div class="hint">Get this from <a href="https://t.me/BotFather" target="_blank" style="color:var(--forge)">@BotFather</a> on Telegram</div>
          <div id="token-validation" style="margin-top:10px;display:none;">
            <div id="token-validating" style="color:var(--dim);font-size:0.82rem;display:none;">⏳ Validating token...</div>
            <div id="token-valid" style="color:var(--green);font-size:0.82rem;display:none;">✅ Valid! Bot: <span id="token-bot-name"></span></div>
            <div id="token-invalid" style="color:var(--red);font-size:0.82rem;display:none;">❌ Invalid token. Check with @BotFather.</div>
          </div>
        </div>
      </div>
      <div class="credentials-fields" id="creds-whatsapp">
        <!-- WhatsApp mode selector -->
        <input type="hidden" name="whatsapp_mode" id="whatsapp_mode_input" value="easy">
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:20px;">
          <label id="wa-mode-easy-label" style="cursor:pointer;">
            <input type="radio" name="whatsapp_mode_ui" value="easy" checked="" data-onchange="toggleWaMode" data-arg="easy" style="position:absolute;opacity:0;pointer-events:none;">
            <div id="wa-mode-easy-card" style="padding:16px;border:2px solid var(--forge);background:var(--forge-dim);border-radius:10px;">
              <div style="font-size:1.3rem;margin-bottom:6px;">⚡</div>
              <div style="font-size:0.88rem;font-weight:700;color:var(--text);margin-bottom:4px;">Easy Mode</div>
              <div style="font-size:0.75rem;color:var(--muted);text-transform:none;letter-spacing:0;font-weight:400;">ChatForge provides a number. Zero setup. No Meta Business Account needed.</div>
            </div>
          </label>
          <label id="wa-mode-diy-label" style="cursor:pointer;">
            <input type="radio" name="whatsapp_mode_ui" value="diy" data-onchange="toggleWaMode" data-arg="diy" style="position:absolute;opacity:0;pointer-events:none;">
            <div id="wa-mode-diy-card" style="padding:16px;border:2px solid var(--border);background:var(--surface);border-radius:10px;">
              <div style="font-size:1.3rem;margin-bottom:6px;">🔧</div>
              <div style="font-size:0.88rem;font-weight:700;color:var(--text);margin-bottom:4px;">DIY — Meta API</div>
              <div style="font-size:0.75rem;color:var(--muted);text-transform:none;letter-spacing:0;font-weight:400;">Bring your own Meta WhatsApp Business API credentials.</div>
            </div>
          </label>
        </div>

        <!-- Easy Mode fields -->
        <div id="wa-easy-fields">
          <div style="background:rgba(34,197,94,0.06);border:1px solid rgba(34,197,94,0.2);border-radius:8px;padding:12px 14px;">
            <p style="font-family:'DM Sans',sans-serif;font-size:0.8rem;color:var(--muted);text-transform:none;letter-spacing:0;font-weight:400;margin:0;">
              ✅ <strong style="color:var(--text);">Zero configuration</strong> — ChatForge assigns a WhatsApp number automatically when you deploy. No Meta Business Account needed.
            </p>
          </div>
        </div>

        <!-- DIY Meta API fields -->
        <div id="wa-diy-fields" style="display:none;">
          <div style="background:rgba(255,77,28,0.06);border:1px solid rgba(201,74,30,0.15);border-radius:8px;padding:14px 16px;margin-bottom:16px;">
            <p style="font-family:'DM Sans',sans-serif;font-size:0.82rem;color:var(--muted);text-transform:none;letter-spacing:0;font-weight:400;margin:0 0 8px;">
              <strong style="color:var(--text);">Prerequisites:</strong> A <strong style="color:var(--text);">Meta Business Account</strong> with a verified phone number in your WhatsApp Business App.
            </p>
            <p style="font-family:'DM Sans',sans-serif;font-size:0.82rem;color:var(--muted);text-transform:none;letter-spacing:0;font-weight:400;margin:0;">
              Go to <strong style="color:var(--text);">Meta for Developers → Your App → WhatsApp → API Setup</strong>.
            </p>
          </div>
          <div class="form-group">
            <label for="channel_id_whatsapp">Phone Number ID *</label>
            <input type="text" id="channel_id_whatsapp" placeholder="1234567890123456">
            <div class="hint">Found in <strong>Meta Developers → WhatsApp → API Setup → Phone Number ID</strong></div>
          </div>
          <div class="form-group">
            <label for="channel_token_whatsapp">Permanent Access Token *</label>
            <input type="text" id="channel_token_whatsapp" placeholder="EAAxxxxxxxxxxxxxxxxxxxxxxxx">
            <div class="hint">Create a <strong>System User</strong> in Meta Business Manager and generate a permanent token with <code style="background:var(--panel);padding:1px 4px;border-radius:3px;">whatsapp_business_messaging</code> permission</div>
          </div>
          <div style="background:rgba(100,200,255,0.06);border:1px solid rgba(100,200,255,0.15);border-radius:8px;padding:12px 14px;margin-top:4px;">
            <p style="font-family:'DM Sans',sans-serif;font-size:0.8rem;color:var(--muted);text-transform:none;letter-spacing:0;font-weight:400;margin:0;">
              💡 After deploying, you'll receive a <strong style="color:var(--text);">Webhook URL</strong> and <strong style="color:var(--text);">Verify Token</strong> to configure in Meta Developers → WhatsApp → Configuration → Webhooks.
            </p>
          </div>
        </div>
      </div>
      <div class="credentials-fields hidden" id="creds-discord">
        <div style="background:rgba(88,101,242,0.08);border:1px solid rgba(88,101,242,0.25);border-radius:8px;padding:14px 16px;margin-bottom:16px;">
          <p style="font-family:'DM Sans',sans-serif;font-size:0.84rem;color:var(--text);text-transform:none;letter-spacing:0;font-weight:600;margin:0 0 8px;">Step 1 — Invite the ChatForge bot to your server</p>
          <p style="font-family:'DM Sans',sans-serif;font-size:0.8rem;color:var(--muted);text-transform:none;letter-spacing:0;font-weight:400;margin:0 0 12px;">The bot needs to be in your server before it can listen to messages.</p>
          <button type="button" id="discord-invite-btn" data-action="openDiscordInvite" style="background:rgba(88,101,242,0.18);border:1px solid rgba(88,101,242,0.4);color:#8b9cf7;border-radius:7px;padding:9px 16px;font-size:0.82rem;font-weight:600;cursor:pointer;font-family:'DM Sans',sans-serif;">🎮 Invite ChatForge Bot →</button>
          <span id="discord-invite-loading" style="display:none;font-size:0.78rem;color:var(--dim);margin-left:10px;">Loading...</span>
        </div>
        <div class="form-group">
          <label for="channel_id_discord">Discord Channel ID <span style="color:var(--forge);">*</span></label>
          <input type="text" id="channel_id_discord" placeholder="1234567890123456789" style="font-family:'DM Sans',sans-serif;">
          <div class="hint">
            <strong>Step 2 —</strong> Right-click a channel in Discord → <strong>Copy Channel ID</strong><br>
            <span style="font-size:0.78rem;color:var(--dim);">(Enable Developer Mode: Discord Settings → Advanced → Developer Mode)</span>
          </div>
          <div id="discord-channel-validation" style="margin-top:10px;display:none;">
            <div id="discord-channel-validating" style="color:var(--dim);font-size:0.82rem;display:none;">⏳ Checking channel access...</div>
            <div id="discord-channel-valid" style="color:var(--green);font-size:0.82rem;display:none;">✅ Channel found: <strong id="discord-channel-name"></strong></div>
            <div id="discord-channel-invalid" style="color:var(--red);font-size:0.82rem;display:none;">❌ <span id="discord-channel-error">Channel not found. Make sure the ChatForge bot is in your server.</span></div>
          </div>
        </div>
        <div style="background:rgba(74,214,160,0.06);border:1px solid rgba(74,214,160,0.15);border-radius:8px;padding:12px 14px;margin-top:4px;">
          <p style="font-family:'DM Sans',sans-serif;font-size:0.8rem;color:var(--muted);text-transform:none;letter-spacing:0;font-weight:400;margin:0;">
            💡 Your agent will reply to <strong style="color:var(--text);">every message</strong> posted in the selected channel. Create a dedicated channel like <code style="background:var(--panel);padding:1px 5px;border-radius:3px;">#ai-support</code> for best results.
          </p>
        </div>
      </div>
      <div class="credentials-fields hidden" id="creds-slack">
        <!-- Slack mode selector: Easy (OAuth) vs DIY (manual token) -->
        <input type="hidden" name="slack_oauth_mode" id="slack_oauth_mode_input" value="">
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:20px;">
          <label id="slack-mode-easy-label" style="cursor:pointer;">
            <input type="radio" name="slack_mode_ui" value="easy" checked="" data-onchange="toggleSlackMode" data-arg="easy" style="position:absolute;opacity:0;pointer-events:none;">
            <div id="slack-mode-easy-card" style="padding:16px;border:2px solid var(--forge);background:var(--forge-dim);border-radius:10px;">
              <div style="font-size:1.3rem;margin-bottom:6px;">⚡</div>
              <div style="font-size:0.88rem;font-weight:700;color:var(--text);margin-bottom:4px;">Easy Mode</div>
              <div style="font-size:0.75rem;color:var(--muted);text-transform:none;letter-spacing:0;font-weight:400;">ChatForge installs to your workspace automatically. One click, no manual setup.</div>
            </div>
          </label>
          <label id="slack-mode-diy-label" style="cursor:pointer;">
            <input type="radio" name="slack_mode_ui" value="diy" data-onchange="toggleSlackMode" data-arg="diy" style="position:absolute;opacity:0;pointer-events:none;">
            <div id="slack-mode-diy-card" style="padding:16px;border:2px solid var(--border);background:var(--surface);border-radius:10px;">
              <div style="font-size:1.3rem;margin-bottom:6px;">🔧</div>
              <div style="font-size:0.88rem;font-weight:700;color:var(--text);margin-bottom:4px;">DIY — Your App</div>
              <div style="font-size:0.75rem;color:var(--muted);text-transform:none;letter-spacing:0;font-weight:400;">Bring your own Slack app and bot token for full control.</div>
            </div>
          </label>
        </div>

        <!-- Easy Mode: OAuth install flow -->
        <div id="slack-easy-fields">
          <!-- Hidden fields populated by OAuth postMessage -->
          <input type="hidden" name="slack_oauth_token" id="slack_oauth_token" value="">
          <input type="hidden" name="slack_team_id" id="slack_team_id" value="">
          <input type="hidden" name="slack_workspace_name" id="slack_workspace_name" value="">

          <div id="slack-oauth-button-area">
            <div style="background:rgba(74,144,226,0.06);border:1px solid rgba(74,144,226,0.18);border-radius:8px;padding:14px 16px;margin-bottom:16px;">
              <p style="font-family:'DM Sans',sans-serif;font-size:0.82rem;color:var(--muted);text-transform:none;letter-spacing:0;font-weight:400;margin:0;">
                ✅ <strong style="color:var(--text);">Zero configuration</strong> — click below to install the ChatForge Slack app to your workspace. Your agent activates immediately.
              </p>
            </div>
            <button type="button" id="slack-oauth-btn" data-action="startSlackOAuth" style="background:rgba(74,144,226,0.18);border:1px solid rgba(74,144,226,0.4);color:#7ab3f0;border-radius:7px;padding:11px 20px;font-size:0.86rem;font-weight:700;cursor:pointer;font-family:'DM Sans',sans-serif;display:flex;align-items:center;gap:8px;">
              💼 Add to Slack →
            </button>
            <span id="slack-oauth-loading" style="display:none;font-size:0.8rem;color:var(--dim);margin-left:12px;">Opening Slack authorization...</span>
          </div>

          <div id="slack-oauth-success-area" style="display:none;">
            <div style="background:rgba(34,197,94,0.06);border:1px solid rgba(34,197,94,0.2);border-radius:8px;padding:14px 16px;">
              <p style="font-family:'DM Sans',sans-serif;font-size:0.88rem;color:var(--text);text-transform:none;letter-spacing:0;font-weight:700;margin:0 0 4px;">✅ Connected to Slack</p>
              <p style="font-family:'DM Sans',sans-serif;font-size:0.82rem;color:var(--muted);text-transform:none;letter-spacing:0;font-weight:400;margin:0;">Workspace: <strong style="color:var(--text);" id="slack-workspace-display"></strong> — ready to deploy!</p>
            </div>
            <button type="button" data-action="resetSlackOAuth" style="margin-top:10px;background:none;border:1px solid var(--border);color:var(--dim);border-radius:6px;padding:6px 12px;font-size:0.78rem;cursor:pointer;font-family:'DM Sans',sans-serif;">
              Use a different workspace
            </button>
          </div>

          <div id="slack-oauth-error-area" style="display:none;">
            <div style="background:rgba(239,68,68,0.06);border:1px solid rgba(239,68,68,0.2);border-radius:8px;padding:12px 14px;">
              <p style="font-family:'DM Sans',sans-serif;font-size:0.82rem;color:#f87171;text-transform:none;letter-spacing:0;font-weight:400;margin:0;">❌ <span id="slack-oauth-error-msg">Authorization failed. Please try again.</span></p>
            </div>
            <button type="button" id="slack-oauth-retry-btn" data-action="startSlackOAuth" style="margin-top:10px;background:rgba(74,144,226,0.18);border:1px solid rgba(74,144,226,0.4);color:#7ab3f0;border-radius:7px;padding:9px 16px;font-size:0.82rem;font-weight:700;cursor:pointer;font-family:'DM Sans',sans-serif;">
              Try Again →
            </button>
          </div>
        </div>

        <!-- DIY Mode: manual bot token -->
        <div id="slack-diy-fields" style="display:none;">
          <div style="background:rgba(74,144,226,0.06);border:1px solid rgba(74,144,226,0.18);border-radius:8px;padding:14px 16px;margin-bottom:16px;">
            <p style="font-family:'DM Sans',sans-serif;font-size:0.82rem;color:var(--muted);text-transform:none;letter-spacing:0;font-weight:400;margin:0 0 6px;">
              <strong style="color:var(--text);">Prerequisites:</strong> Create a <strong style="color:var(--text);">Slack App</strong> at <a href="https://api.slack.com/apps" target="_blank" style="color:var(--forge)">api.slack.com/apps</a> and enable <strong style="color:var(--text);">Events API</strong>.
            </p>
            <p style="font-family:'DM Sans',sans-serif;font-size:0.82rem;color:var(--muted);text-transform:none;letter-spacing:0;font-weight:400;margin:0;">
              After deploying, copy your webhook URL into your Slack App's <strong style="color:var(--text);">Event Subscriptions → Request URL</strong> to go live.
            </p>
          </div>
          <div class="form-group">
            <label for="channel_token_slack">Bot Token</label>
            <input type="text" id="channel_token_slack" placeholder="xoxb-your-bot-token">
            <div class="hint">From <a href="https://api.slack.com/apps" target="_blank" style="color:var(--forge)">Slack API</a> → Your App → OAuth &amp; Permissions → Bot User OAuth Token</div>
            <div id="slack-token-validation" style="margin-top:10px;display:none;">
              <div id="slack-token-validating" style="color:var(--dim);font-size:0.82rem;display:none;">⏳ Validating token...</div>
              <div id="slack-token-valid" style="color:var(--green);font-size:0.82rem;display:none;">✅ Valid! Workspace: <span id="slack-team-name"></span></div>
              <div id="slack-token-invalid" style="color:var(--red);font-size:0.82rem;display:none;">❌ Invalid token. Check your Bot Token from api.slack.com.</div>
            </div>
          </div>
          <div class="form-group">
            <label for="channel_id_slack">Signing Secret <span style="color:var(--dim);font-weight:400;font-size:0.8rem;">(optional but recommended)</span></label>
            <input type="text" id="channel_id_slack" placeholder="abc123def456...">
            <div class="hint">From <a href="https://api.slack.com/apps" target="_blank" style="color:var(--forge)">Slack API</a> → Your App → Basic Information → Signing Secret — verifies incoming events</div>
          </div>
          <div style="background:rgba(255,77,28,0.06);border:1px solid rgba(255,77,28,0.12);border-radius:8px;padding:12px 14px;margin-top:4px;">
            <p style="font-family:'DM Sans',sans-serif;font-size:0.8rem;color:var(--muted);text-transform:none;letter-spacing:0;font-weight:400;margin:0;">
              💡 After deploying, set your <strong style="color:var(--text);">Request URL</strong> in Slack's Event Subscriptions. Subscribe to <code style="background:var(--panel);padding:1px 5px;border-radius:3px;">message.im</code> and <code style="background:var(--panel);padding:1px 5px;border-radius:3px;">app_mention</code> events.
            </p>
          </div>
        </div>
      </div>

      <div class="credentials-fields hidden" id="creds-email">
        <div style="background:rgba(74,214,160,0.06);border:1px solid rgba(74,214,160,0.18);border-radius:8px;padding:14px 16px;margin-bottom:16px;">
          <p style="font-family:'DM Sans',sans-serif;font-size:0.82rem;color:var(--muted);text-transform:none;letter-spacing:0;font-weight:400;margin:0 0 6px;">
            <strong style="color:var(--text);">How it works:</strong> Your agent monitors your inbox every 2 minutes, auto-responds to new emails, and sends replies via SMTP. Use an <strong style="color:var(--text);">app password</strong> (not your regular password) for Gmail/Outlook.
          </p>
          <p style="font-family:'DM Sans',sans-serif;font-size:0.82rem;color:var(--muted);text-transform:none;letter-spacing:0;font-weight:400;margin:0;">
            Gmail: <a href="https://myaccount.google.com/apppasswords" target="_blank" style="color:var(--forge)">Create App Password</a> (requires 2FA) • Enable IMAP in Gmail Settings → Forwarding and POP/IMAP
          </p>
        </div>
        <div class="form-group">
          <label for="email_provider_select">Email Provider</label>
          <select id="email_provider_select" name="email_provider" style="width:100%;padding:10px 14px;background:var(--panel);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:0.9rem;cursor:pointer;">
            <option value="gmail">Gmail (imap.gmail.com)</option>
            <option value="outlook">Outlook / Hotmail (outlook.office365.com)</option>
            <option value="yahoo">Yahoo Mail (imap.mail.yahoo.com)</option>
            <option value="custom">Custom / Other</option>
          </select>
        </div>
        <div class="form-group">
          <label for="email_address">Email Address *</label>
          <input type="email" id="email_address" name="email_address" placeholder="you@gmail.com" required="">
          <div class="hint">This is your IMAP username and the address the agent will reply from</div>
        </div>
        <div class="form-group">
          <label for="email_password">App Password *</label>
          <input type="password" id="email_password" name="email_password" placeholder="App password (not your regular password)" required="">
          <div class="hint">Use an app-specific password — not your main account password</div>
        </div>
        <div id="email-custom-settings" style="display:none;">
          <div class="form-group">
            <label>IMAP Settings</label>
            <div style="display:grid;grid-template-columns:1fr auto;gap:8px;">
              <input type="text" id="email_imap_host" name="email_imap_host" placeholder="imap.example.com" style="width:100%;">
              <input type="number" id="email_imap_port" name="email_imap_port" placeholder="993" value="993" style="width:80px;">
            </div>
            <div class="hint">IMAP host and port (993 for TLS)</div>
          </div>
          <div class="form-group">
            <label>SMTP Settings</label>
            <div style="display:grid;grid-template-columns:1fr auto;gap:8px;">
              <input type="text" id="email_smtp_host" name="email_smtp_host" placeholder="smtp.example.com" style="width:100%;">
              <input type="number" id="email_smtp_port" name="email_smtp_port" placeholder="587" value="587" style="width:80px;">
            </div>
            <div class="hint">SMTP host and port (587 for STARTTLS, 465 for SSL)</div>
          </div>
        </div>
        <div style="margin-top:8px;">
          <button type="button" id="email-test-btn" data-action="testEmailCredentials" style="background:var(--panel);border:1px solid var(--border);color:var(--text);padding:8px 16px;border-radius:6px;cursor:pointer;font-size:0.85rem;">🔗 Test Connection</button>
          <span id="email-test-result" style="margin-left:12px;font-size:0.82rem;display:none;"></span>
        </div>
      </div>

      <div class="credentials-fields hidden" id="creds-webchat">
        <div style="background:rgba(0,200,255,0.06);border:1px solid rgba(0,200,255,0.18);border-radius:8px;padding:14px 16px;margin-bottom:16px;">
          <p style="font-family:'DM Sans',sans-serif;font-size:0.82rem;color:var(--muted);text-transform:none;letter-spacing:0;font-weight:400;margin:0 0 6px;">
            <strong style="color:var(--text);">How it works:</strong> Deploy your agent and paste one line of code into any website. A floating chat bubble appears instantly — no backend setup required.
          </p>
          <p style="font-family:'DM Sans',sans-serif;font-size:0.82rem;color:var(--muted);text-transform:none;letter-spacing:0;font-weight:400;margin:0;">
            After deploying, you'll receive a <strong style="color:var(--text);">&lt;script&gt; embed snippet</strong> to copy into your site's HTML.
          </p>
        </div>

        <!-- Widget Customization -->
        <div style="margin-bottom:14px;">
          <div style="font-family:'DM Sans',sans-serif;font-size:0.72rem;color:var(--dim);text-transform:uppercase;letter-spacing:1px;margin-bottom:12px;">🎨 Widget Appearance</div>

          <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px;">
            <div class="form-group" style="margin-bottom:0;">
              <label for="webchat_primary_color" style="font-size:0.78rem;color:var(--muted);margin-bottom:4px;display:block;">Primary Color</label>
              <div style="display:flex;align-items:center;gap:8px;">
                <input type="color" id="webchat_primary_color" name="webchat_primary_color" value="#ff4d1c" style="width:42px;height:34px;padding:2px;border:1px solid var(--border);border-radius:6px;background:var(--panel);cursor:pointer;">
                <input type="text" id="webchat_primary_color_hex" placeholder="#ff4d1c" style="flex:1;font-family:'DM Sans',sans-serif;font-size:0.82rem;" data-oninput="syncColorPicker" value="#ff4d1c">
              </div>
              <div class="hint">Chat bubble &amp; accent color</div>
            </div>
            <div class="form-group" style="margin-bottom:0;">
              <label for="webchat_bot_name" style="font-size:0.78rem;color:var(--muted);margin-bottom:4px;display:block;">Display Name <span style="color:var(--dim);">(optional)</span></label>
              <input type="text" id="webchat_bot_name" name="webchat_bot_name" placeholder="Uses agent name by default" maxlength="40">
              <div class="hint">Name shown in chat header</div>
            </div>
          </div>

          <div class="form-group" style="margin-bottom:0;">
            <label for="webchat_welcome_message" style="font-size:0.78rem;color:var(--muted);margin-bottom:4px;display:block;">Welcome Message <span style="color:var(--dim);">(optional)</span></label>
            <input type="text" id="webchat_welcome_message" name="webchat_welcome_message" placeholder="👋 Hi there! How can I help you today?" maxlength="200">
            <div class="hint">First message visitors see when they open the chat</div>
          </div>
        </div>

        <div style="margin-bottom:14px;">
          <div style="font-family:'DM Sans',sans-serif;font-size:0.72rem;color:var(--dim);text-transform:uppercase;letter-spacing:1px;margin-bottom:8px;">🔒 Security <span style="color:var(--dim);font-size:0.65rem;text-transform:none;letter-spacing:0;font-weight:400;">(optional)</span></div>
          <div class="form-group" style="margin-bottom:0;">
            <label for="webchat_allowed_domains" style="font-size:0.78rem;color:var(--muted);margin-bottom:4px;display:block;">Allowed Domains</label>
            <input type="text" id="webchat_allowed_domains" name="webchat_allowed_domains" placeholder="e.g. mysite.com, app.mysite.com">
            <div class="hint">Comma-separated domains. Leave blank to allow all domains.</div>
          </div>
        </div>

        <div style="background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:12px 14px;margin-bottom:12px;">
          <div style="font-family:'DM Sans',sans-serif;font-size:0.72rem;color:var(--dim);text-transform:uppercase;letter-spacing:1px;margin-bottom:8px;">Preview embed code</div>
          <code style="font-family:'DM Sans',sans-serif;font-size:0.78rem;color:var(--forge);word-break:break-all;">&lt;script src="https://chatforge.live/widget.js" data-agent="YOUR_AGENT_ID"&gt;&lt;/script&gt;</code>
        </div>
        <div style="background:rgba(255,77,28,0.06);border:1px solid rgba(255,77,28,0.12);border-radius:8px;padding:12px 14px;">
          <p style="font-family:'DM Sans',sans-serif;font-size:0.8rem;color:var(--muted);text-transform:none;letter-spacing:0;font-weight:400;margin:0;">
            💡 <strong style="color:var(--text);">No configuration needed.</strong> Just deploy and you'll get your unique embed snippet. Works on any site — Webflow, Squarespace, WordPress, custom HTML.
          </p>
        </div>

        <script nonce="">
        // Sync color picker ↔ hex input
        document.addEventListener('DOMContentLoaded', function() {
          var colorPicker = document.getElementById('webchat_primary_color');
          var hexInput = document.getElementById('webchat_primary_color_hex');
          if (colorPicker && hexInput) {
            colorPicker.addEventListener('input', function() {
              hexInput.value = colorPicker.value;
            });
          }
        });
        function syncColorPicker(input) {
          var val = input.value.trim();
          if (/^#[0-9a-fA-F]{6}$/.test(val)) {
            var picker = document.getElementById('webchat_primary_color');
            if (picker) picker.value = val;
          }
        }
        </script>
      </div>

      <div class="form-nav">
        <button type="button" class="btn btn-secondary" data-action="goStep" data-arg="1">← Back</button>
        <button type="button" class="btn btn-primary" data-action="goStep" data-arg="3">Next: Guardrails →</button>
      </div>
    </div>

    <!-- Step 3: Guardrails -->
    <div class="form-section active" data-step="3">
      <div class="guardrail-section-label">🛡 Safety Settings</div>

      <!-- Blocked Topics -->
      <div class="guardrail-block">
        <h4>Blocked Topics</h4>
        <p class="block-hint">Topics your agent should never discuss. Comma-separated list (e.g. "politics, competitor pricing, medical advice").</p>
        <div class="form-group" style="margin-bottom:0">
          <input type="text" id="blocked_topics" name="blocked_topics" placeholder="e.g. politics, competitor pricing, refund policy, medical advice">
          <div class="hint">Leave blank to allow all topics</div>
        </div>
      </div>

      <!-- Boundary Rules -->
      <div class="guardrail-block">
        <h4>Boundary Rules <span class="guardrail-badge">Toggle</span></h4>
        <p class="block-hint">Pre-built safety rules. Toggle on to enforce each constraint.</p>
        <div class="toggle-list">
          <label class="toggle-row">
            <input type="checkbox" name="rule_no_promises" id="rule_no_promises" value="1">
            <div class="toggle-switch"></div>
            <div class="toggle-label">
              Don't make promises or commitments
              <span>Agent won't say "I promise", "I guarantee", or similar phrases</span>
            </div>
          </label>
          <label class="toggle-row">
            <input type="checkbox" name="rule_no_unlisted_pricing" id="rule_no_unlisted_pricing" value="1">
            <div class="toggle-switch"></div>
            <div class="toggle-label">
              Don't share pricing not listed in instructions
              <span>Agent won't invent or confirm prices not in its configuration</span>
            </div>
          </label>
          <label class="toggle-row">
            <input type="checkbox" name="rule_stay_on_topic" id="rule_stay_on_topic" value="1">
            <div class="toggle-switch"></div>
            <div class="toggle-label">
              Stay on-topic only (don't go off-script)
              <span>Agent will redirect off-topic questions back to its purpose</span>
            </div>
          </label>
          <label class="toggle-row">
            <input type="checkbox" name="rule_escalate_if_uncertain" id="rule_escalate_if_uncertain" value="1">
            <div class="toggle-switch"></div>
            <div class="toggle-label">
              Escalate to human if uncertain
              <span>When the agent doesn't know something, it will say "Let me connect you with our team"</span>
            </div>
          </label>
        </div>
      </div>

      <!-- Agent Capabilities -->
      <div class="guardrail-block" style="border-left:3px solid var(--forge);padding-left:16px;">
        <h4 style="display:flex;align-items:center;gap:8px;">
          🔍 Agent Capabilities
          <span style="font-family:'DM Sans',sans-serif;font-size:0.65rem;font-weight:600;background:var(--forge);color:#fff;padding:2px 7px;border-radius:3px;text-transform:uppercase;letter-spacing:0.5px;">New</span>
        </h4>
        <p class="block-hint">Give your agent access to real-time information from the web.</p>
        <div class="toggle-list">
          <label class="toggle-row">
            <input type="checkbox" name="enable_web_search" id="enable_web_search" value="1">
            <div class="toggle-switch"></div>
            <div class="toggle-label">
              Enable Web Search
              <span>Agent can search the internet mid-conversation — finds businesses, contacts, news, and real-time data. Great for sales bots, support agents, and research assistants. Up to 20 searches/day.</span>
            </div>
          </label>
          <label class="toggle-row">
            <input type="checkbox" name="enable_location_search" id="enable_location_search" value="1">
            <div class="toggle-switch"></div>
            <div class="toggle-label">
              Enable Location Search
              <span>Agent can find nearby places using Google Maps. When users ask about local businesses (restaurants, shops, services), bot asks to share their location. Counts toward the 20 searches/day limit.</span>
            </div>
          </label>
        </div>
      </div>

      <!-- Custom Safety Instructions -->
      <div class="guardrail-block">
        <h4>Custom Safety Instructions</h4>
        <p class="block-hint">Additional rules the agent must follow. Be specific.</p>
        <div class="form-group" style="margin-bottom:0">
          <textarea id="custom_safety_instructions" name="custom_safety_instructions" rows="4" placeholder="e.g. Never say we offer refunds. Always redirect billing questions to support@yourdomain.com. Don't discuss competitor products."></textarea>
          <div class="hint">Plain-language rules injected directly into the agent's system prompt</div>
        </div>
      </div>

      <div class="form-nav">
        <button type="button" class="btn btn-secondary" data-action="goStep" data-arg="2">← Back</button>
        <button type="button" class="btn btn-primary" data-action="goStep" data-arg="4">Next: Voice Agent →</button>
      </div>
    </div>

    <!-- Step 4: Voice Agent -->
    <div class="form-section" data-step="4">
      
      <div style="display:flex;align-items:center;gap:16px;padding:28px;background:var(--panel);border:1px solid var(--border);border-radius:10px;margin-bottom:24px;">
        <div style="font-size:2.5rem;flex-shrink:0;">🔒</div>
        <div>
          <div style="font-family:'Bricolage Grotesque',sans-serif;font-size:1.1rem;text-transform:uppercase;letter-spacing:2px;margin-bottom:6px;">Business Plan Feature</div>
          <div style="font-family:'DM Sans',sans-serif;font-size:0.875rem;color:var(--muted);text-transform:none;letter-spacing:0;font-weight:400;line-height:1.6;margin-bottom:12px;">
            Maya Voice Agent automatically calls leads captured from your chatbot. Available on the <strong style="color:var(--text);">Business plan</strong> at $99/mo.
          </div>
          <a href="/pricing" style="display:inline-flex;align-items:center;gap:6px;padding:8px 16px;background:var(--forge);color:#fff;border-radius:6px;font-size:0.85rem;text-decoration:none;font-weight:600;font-family:'DM Sans',sans-serif;">Upgrade to Business →</a>
        </div>
      </div>
      
      <div class="form-nav">
        <button type="button" class="btn btn-secondary" data-action="goStep" data-arg="3">← Back</button>
        <button type="button" class="btn btn-primary" data-action="goStep" data-arg="5">Next: API Connectors →</button>
      </div>
    </div>

    <!-- Step 5: External API Connectors (Enterprise only) -->
    <div class="form-section" data-step="5">
      <div class="guardrail-section-label">🔌 External API Connectors</div>

      

      
      <div style="display:flex;align-items:center;gap:16px;padding:28px;background:var(--panel);border:1px solid var(--border);border-radius:10px;margin-bottom:24px;">
        <div style="font-size:2.5rem;flex-shrink:0;">🔒</div>
        <div>
          <div style="font-family:'Bricolage Grotesque',sans-serif;font-size:1.1rem;text-transform:uppercase;letter-spacing:2px;margin-bottom:6px;">Enterprise Plan Feature</div>
          <div style="font-family:'DM Sans',sans-serif;font-size:0.875rem;color:var(--muted);text-transform:none;letter-spacing:0;font-weight:400;line-height:1.6;margin-bottom:12px;">
            Connect your agent to any REST or oData API — SAP, Salesforce, HubSpot, or your own backend. Available exclusively on the <strong style="color:var(--text);">Enterprise plan</strong> at $199/mo.
          </div>
          <a href="/pricing" style="display:inline-flex;align-items:center;gap:6px;padding:8px 16px;background:linear-gradient(135deg,#7c3aed,#4f46e5);color:#fff;border-radius:6px;font-size:0.85rem;text-decoration:none;font-weight:600;font-family:'DM Sans',sans-serif;">Upgrade to Enterprise →</a>
        </div>
      </div>
      
      <div class="form-nav">
        <button type="button" class="btn btn-secondary" data-action="goStep" data-arg="4">← Back</button>
        <button type="button" class="btn btn-primary" data-action="goStep" data-arg="6">Next: Review →</button>
      </div>
    </div>

    <!-- Step 6: Review & Deploy -->
    <div class="form-section" data-step="6">
      <div class="review-card">
        <h3>Review Your Agent</h3>
        <div class="review-rows">
          <div>
            <div class="review-label">Name</div>
            <div class="review-value" id="review-name">—</div>
          </div>
          <div>
            <div class="review-label">Channel</div>
            <div class="review-value" id="review-channel">—</div>
          </div>
          <div>
            <div class="review-label">Personality</div>
            <div class="review-value-body" id="review-personality">—</div>
          </div>
          <div>
            <div class="review-label">Instructions</div>
            <div class="review-value-body" id="review-instructions">—</div>
          </div>
          <div id="review-guardrails-row" style="display:none">
            <div class="review-label">🛡 Guardrails</div>
            <div class="review-value-body" id="review-guardrails">—</div>
          </div>
        </div>
      </div>

      <!-- Hidden fields for credentials -->
      <input type="hidden" name="channel_token" id="channel_token_hidden">
      <input type="hidden" name="channel_id" id="channel_id_hidden">

      <div class="form-nav">
        <button type="button" class="btn btn-secondary" data-action="goStep" data-arg="5">← Back</button>
        <button type="submit" class="btn btn-primary btn-lg" id="deploy-btn">⚡ Deploy Agent</button>
      </div>
    </div>
  </form>
</div>