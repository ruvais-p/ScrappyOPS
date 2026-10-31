(function () {
  'use strict';
  const STYLE = `
    .cp-btn{background:transparent;border:1px solid #ffffff40;color:#fff;padding:11px 12px;font-size:13px;text-align:left;border-radius:12px;min-height:44px;width:100%;cursor:pointer}
    .cp-btn:hover{background:#ffffff14}.who>.cp-btn,.me>.cp-btn{width:auto;min-height:36px;padding:7px 10px;font-size:12px}.cp-dialog{border:0;padding:0;background:transparent;max-width:min(92vw,430px);width:100%}.cp-dialog::backdrop{background:#251b1dcc;backdrop-filter:blur(3px)}
    .cp-card{background:#fff;color:#241d1e;border-radius:18px;padding:24px;box-shadow:0 24px 70px #0006;font-family:inherit}.cp-card h2{margin:0 0 6px;font-size:24px}.cp-card p{margin:0 0 18px;color:#686064;font-size:14px}
    .cp-card label{display:block;font-size:12px;font-weight:700;letter-spacing:.04em;margin:13px 0 5px}.cp-card input{box-sizing:border-box;width:100%;padding:12px;border:1.5px solid #cfc8c9;border-radius:10px;font:inherit}.cp-card input:focus{outline:2px solid #8b1e2440;border-color:#8b1e24}
    .cp-error{min-height:20px;color:#a11620;font-size:13px;margin-top:9px}.cp-actions{display:flex;justify-content:flex-end;gap:9px;margin-top:10px}.cp-actions button{border:0;border-radius:10px;padding:11px 16px;font:inherit;font-weight:700;cursor:pointer}.cp-cancel{background:#eee9e9;color:#3d3436}.cp-save{background:#8b1e24;color:#fff}.cp-save:disabled{opacity:.6;cursor:wait}`;

  function accessToken() {
    for (const key of ['scrappy_session', 'scrappy_wh_session', 'scrappy_hq_session', 'scrappy_super_admin_session', 'scrappy_kwd_session']) {
      try { const value = JSON.parse(localStorage.getItem(key)); if (value && value.access_token) return value.access_token; } catch (_) {}
    }
    return '';
  }

  const style = document.createElement('style'); style.textContent = STYLE; document.head.appendChild(style);
  const dialog = document.createElement('dialog'); dialog.className = 'cp-dialog';
  dialog.innerHTML = `<form class="cp-card" method="dialog"><h2>Change password</h2><p>Use 8 to 72 characters. Changing it signs out your other open sessions.</p><label for="cp-current">CURRENT PASSWORD</label><input id="cp-current" type="password" autocomplete="current-password" required><label for="cp-new">NEW PASSWORD</label><input id="cp-new" type="password" autocomplete="new-password" minlength="8" maxlength="72" required><label for="cp-confirm">CONFIRM NEW PASSWORD</label><input id="cp-confirm" type="password" autocomplete="new-password" minlength="8" maxlength="72" required><div class="cp-error" role="alert"></div><div class="cp-actions"><button class="cp-cancel" value="cancel" type="button">Cancel</button><button class="cp-save" type="submit">Change password</button></div></form>`;
  document.body.appendChild(dialog);

  function openDialog() { dialog.querySelector('form').reset(); dialog.querySelector('.cp-error').textContent = ''; dialog.showModal(); setTimeout(() => dialog.querySelector('#cp-current').focus(), 0); }
  dialog.querySelector('.cp-cancel').addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', e => { if (e.target === dialog) dialog.close(); });
  dialog.querySelector('form').addEventListener('submit', async e => {
    e.preventDefault();
    const current = dialog.querySelector('#cp-current').value, password = dialog.querySelector('#cp-new').value, confirm = dialog.querySelector('#cp-confirm').value;
    const error = dialog.querySelector('.cp-error'), save = dialog.querySelector('.cp-save');
    if (password !== confirm) { error.textContent = 'The new passwords do not match.'; return; }
    if (password.length < 8 || password.length > 72) { error.textContent = 'Your new password must be 8 to 72 characters.'; return; }
    save.disabled = true; error.textContent = '';
    try {
      const response = await fetch('/auth/v1/user', { method: 'PATCH', headers: { Authorization: 'Bearer ' + accessToken(), 'Content-Type': 'application/json' }, body: JSON.stringify({ current_password: current, password }) });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.message || data.msg || 'Could not change your password.');
      dialog.close();
      if (typeof toast === 'function') toast('Password changed successfully.');
      else window.alert('Password changed successfully.');
    } catch (err) { error.textContent = err.message; }
    finally { save.disabled = false; }
  });

  function addButtons() {
    document.querySelectorAll('[data-act="logout"], [data-nav="signout"]').forEach(logout => {
      if (logout.hasAttribute('data-password-native')) return;
      if (logout.previousElementSibling && logout.previousElementSibling.dataset.changePassword !== undefined) return;
      const button = document.createElement('button'); button.type = 'button';
      button.className = 'cp-btn' + (logout.classList.contains('mob-only') ? ' mob-only' : '');
      button.dataset.changePassword = ''; button.textContent = 'Change password';
      logout.parentNode.insertBefore(button, logout);
    });
  }
  document.addEventListener('click', e => { if (e.target.closest('[data-change-password]')) openDialog(); });
  addButtons(); new MutationObserver(addButtons).observe(document.body, { childList: true, subtree: true });
})();
