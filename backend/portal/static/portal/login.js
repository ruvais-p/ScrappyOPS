/* The one login page. It sends the email and password to /login/; the server answers with the person's dashboard and the
   login to keep in the browser. Nothing else happens here. */
(function () {
  var form = document.getElementById('login-form')
  var email = document.getElementById('email')
  var pw = document.getElementById('password')
  var err = document.getElementById('login-err')
  var btn = document.getElementById('login-btn')
  var toggle = document.getElementById('pwtoggle')

  // a message passed in the address (for example "You were logged out…") is shown, then removed from the address bar
  if (err.textContent.trim()) { try { history.replaceState(null, '', location.pathname) } catch (e) { /* fine */ } }

  toggle.addEventListener('click', function () {
    var show = pw.type === 'password'
    pw.type = show ? 'text' : 'password'
    toggle.setAttribute('aria-label', show ? 'Hide password' : 'Show password')
  })

  form.addEventListener('submit', function (ev) {
    ev.preventDefault()
    err.textContent = ''
    var e = email.value.trim(), p = pw.value
    if (!e || !p) { err.textContent = 'Enter your email and password.'; return }
    btn.disabled = true
    btn.textContent = 'Signing in…'
    fetch('/login/', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: e, password: p }) })
      .then(function (r) { return r.json().catch(function () { return {} }).then(function (d) { return { ok: r.ok, d: d } }) })
      .then(function (res) {
        if (!res.ok) throw new Error(res.d.error || 'Login failed. Try again.')
        var d = res.d
        // one login in the browser: remove any earlier dashboard's login, then store this one
        try {
          d.all_storage_keys.forEach(function (k) { localStorage.removeItem(k) })
          localStorage.setItem(d.storage_key, JSON.stringify(d.session))
        } catch (x) { throw new Error('This browser blocks storage, so the dashboard cannot stay signed in. Allow site data and try again.') }
        location.replace(d.redirect)
      })
      .catch(function (x) {
        err.textContent = x.message || 'Login failed. Try again.'
        btn.disabled = false
        btn.textContent = 'Sign in'
      })
  })
})()
