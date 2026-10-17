import { motion } from 'motion/react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import './LandingPage.css'

const MASCOT_URL = '/mascot.png'

export function LandingPage() {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)

  return (
    <div className="piko-landing">
      {/* 1. Header / Navigation */}
      <header className="piko-landing-header">
        <div className="piko-landing-header-inner">
          <Link to="/" className="piko-landing-brand" aria-label="Piko home">
            <div className="piko-landing-brand-logo">
              <img src={MASCOT_URL} alt="Piko mascot" />
            </div>
            <div>
              <span className="piko-landing-brand-title">
                Piko
                <span className="piko-badge-pulse" style={{ display: 'inline-block' }} />
              </span>
              <span className="piko-landing-brand-badge">Family Safety</span>
            </div>
          </Link>

          <nav className="piko-landing-nav" aria-label="Main navigation">
            <a href="#features">Features</a>
            <a href="#how-it-works">How it works</a>
            <a href="#hosting-options">Hosting &amp; Pricing</a>
            <a href="#matrix">Comparison</a>
            <a href="#privacy">Privacy</a>
            <a href="#faq">FAQ</a>
          </nav>

          <div className="piko-landing-header-actions">
            <Link to="/login" className="piko-btn-secondary" style={{ padding: '8px 18px', fontSize: '0.85rem' }}>
              Sign in
            </Link>
            <Link to="/login" className="piko-btn-primary" style={{ padding: '8px 20px', fontSize: '0.85rem' }}>
              Get started
            </Link>
            <button
              type="button"
              className="piko-btn-secondary"
              aria-label="Toggle navigation menu"
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              style={{ padding: '8px 12px', fontSize: '1rem', display: 'none' }}
              id="piko-mobile-toggle"
            >
              {mobileMenuOpen ? '✕' : '☰'}
            </button>
          </div>
        </div>

        {mobileMenuOpen && (
          <div
            style={{
              maxWidth: 1140,
              margin: '8px auto 0 auto',
              background: 'rgba(250, 248, 244, 0.98)',
              borderRadius: 24,
              padding: '16px 24px',
              boxShadow: 'var(--lp-shadow-float)',
              display: 'flex',
              flexDirection: 'column',
              gap: 12,
            }}
          >
            <a href="#features" onClick={() => setMobileMenuOpen(false)}>Features</a>
            <a href="#how-it-works" onClick={() => setMobileMenuOpen(false)}>How it works</a>
            <a href="#hosting-options" onClick={() => setMobileMenuOpen(false)}>Hosting &amp; Pricing</a>
            <a href="#matrix" onClick={() => setMobileMenuOpen(false)}>Comparison</a>
            <a href="#privacy" onClick={() => setMobileMenuOpen(false)}>Privacy</a>
            <a href="#faq" onClick={() => setMobileMenuOpen(false)}>FAQ</a>
          </div>
        )}
      </header>

      {/* 2. Hero Section */}
      <section className="piko-hero" id="hero">
        <div className="piko-hero-grid">
          {/* Left Hero Content */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, ease: 'easeOut' }}
          >
            <div className="piko-badge">
              <span className="piko-badge-pulse" />
              <span>Connected by care · Protected with choice</span>
            </div>

            <h1 className="piko-hero-title">
              A little more peace of mind. <br />
              <span className="piko-gradient-text">A lot more freedom.</span>
            </h1>

            <p className="piko-hero-sub">
              Stay connected with your family through Piko. Get the convenience of a managed hosted service for your
              household, or self-host it freely on your own hardware for complete telemetry custody.
            </p>

            <div className="piko-hero-ctas">
              <Link to="/login" className="piko-btn-primary" style={{ padding: '14px 28px', fontSize: '1rem' }}>
                <span>Get started with Piko</span>
                <span aria-hidden="true">→</span>
              </Link>
              <a href="#hosting-options" className="piko-btn-secondary" style={{ padding: '14px 24px', fontSize: '1rem' }}>
                <span>Explore hosting options</span>
              </a>
            </div>

            <div className="piko-hero-footnote">
              <span style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--lp-mint-dark)' }} />
              <span>Your family. Your choice. Zero vendor lock-in.</span>
            </div>
          </motion.div>

          {/* Right Mascot Stage */}
          <div className="piko-stage-wrapper">
            <motion.div
              className="piko-stage-orb"
              animate={{ y: [0, -8, 0] }}
              transition={{ duration: 5, repeat: Infinity, ease: 'easeInOut' }}
            >
              <motion.img
                src={MASCOT_URL}
                alt="Piko official friendly mascot"
                className="piko-mascot-img"
                animate={{ rotate: [0, 1.5, 0, -1.5, 0] }}
                transition={{ duration: 7, repeat: Infinity, ease: 'easeInOut' }}
              />

              {/* Floating Live Telemetry Chip 1 */}
              <motion.div
                className="piko-float-chip piko-float-chip-1"
                animate={{ y: [0, -6, 0] }}
                transition={{ duration: 4, repeat: Infinity, ease: 'easeInOut', delay: 0.5 }}
              >
                <div className="piko-chip-icon" style={{ background: 'var(--lp-mint)', color: 'var(--lp-mint-dark)' }}>
                  ✓
                </div>
                <div>
                  <div className="piko-chip-title">Safe Zone Verified</div>
                  <div className="piko-chip-sub">Greenwood Campus · Synced</div>
                </div>
              </motion.div>

              {/* Floating Live Telemetry Chip 2 */}
              <motion.div
                className="piko-float-chip piko-float-chip-2"
                animate={{ y: [0, 6, 0] }}
                transition={{ duration: 4.5, repeat: Infinity, ease: 'easeInOut', delay: 1 }}
              >
                <div className="piko-chip-icon" style={{ background: 'var(--lp-softblue)', color: 'var(--lp-blue)' }}>
                  📱
                </div>
                <div>
                  <div className="piko-chip-title">Aarav · At School</div>
                  <div className="piko-chip-sub">84% Battery · Fresh 12s ago</div>
                </div>
              </motion.div>
            </motion.div>
          </div>
        </div>
      </section>

      {/* 3. Core Trust Principles */}
      <section className="piko-section" style={{ borderTop: '1px solid var(--lp-border)', background: 'rgba(255,255,255,0.4)' }}>
        <div className="piko-section-header" style={{ marginBottom: 36 }}>
          <span className="piko-section-tag">Core Principles</span>
          <h2 className="piko-section-title">Safety grounded in mutual trust</h2>
          <p className="piko-section-desc">Protective care designed for real families, not stealth surveillance.</p>
        </div>
        <div className="piko-principles-grid">
          <div className="piko-clay-card">
            <div className="piko-card-icon" style={{ background: 'var(--lp-softblue)', color: 'var(--lp-blue)' }}>
              📍
            </div>
            <h3 className="piko-card-title">Stay genuinely connected</h3>
            <p className="piko-card-desc">
              Useful, low-latency location sharing and lightweight family messaging designed for daily reassurance without constant friction.
            </p>
          </div>

          <div className="piko-clay-card">
            <div className="piko-card-icon" style={{ background: 'var(--lp-mint)', color: 'var(--lp-mint-dark)' }}>
              🤝
            </div>
            <h3 className="piko-card-title">Respect independence</h3>
            <p className="piko-card-desc">
              Mutual family transparency. Children see what parents see — never treated as objects to silently track with stealth stalkerware.
            </p>
          </div>

          <div className="piko-clay-card">
            <div className="piko-card-icon" style={{ background: 'var(--lp-primary-tint)', color: 'var(--lp-primary)' }}>
              🛡️
            </div>
            <h3 className="piko-card-title">Choose your setup</h3>
            <p className="piko-card-desc">
              Zero lock-in. Subscribe to managed Piko Hosted, or self-host your own server on your personal homelab hardware whenever you want.
            </p>
          </div>
        </div>
      </section>

      {/* 4. How Piko Works */}
      <section className="piko-section" id="how-it-works">
        <div className="piko-section-header">
          <span className="piko-section-tag">Simple by Design</span>
          <h2 className="piko-section-title">How Piko brings your family closer</h2>
          <p className="piko-section-desc">
            Straightforward setup for parents and children, without technical confusion or intimidating surveillance screens.
          </p>
        </div>

        <div className="piko-steps-grid">
          <div className="piko-clay-card">
            <div className="piko-step-num">01</div>
            <h3 className="piko-card-title">Set up your family</h3>
            <p className="piko-card-desc">
              Create your private family space. Pair devices with a transparent, mutual QR code or invite link so everyone understands what is shared.
            </p>
            <div style={{ marginTop: 'auto', paddingTop: 16, fontSize: '0.8rem', fontWeight: 700, color: 'var(--lp-mint-dark)' }}>
              ✓ Takes under 2 minutes
            </div>
          </div>

          <div className="piko-clay-card">
            <div className="piko-step-num">02</div>
            <h3 className="piko-card-title">Stay connected gently</h3>
            <p className="piko-card-desc">
              View battery status, transparent location freshness, geofence updates, and quick reassuring check-ins like "I'm okay" or "Arrived safely".
            </p>
            <div style={{ marginTop: 'auto', paddingTop: 16, fontSize: '0.8rem', fontWeight: 700, color: 'var(--lp-primary)' }}>
              ✓ Offline-aware sync
            </div>
          </div>

          <div className="piko-clay-card">
            <div className="piko-step-num">03</div>
            <h3 className="piko-card-title">Choose how it runs</h3>
            <p className="piko-card-desc">
              Let us maintain the cloud and updates with Piko Hosted, or run your own instance via Docker on home hardware with our self-hosted stack.
            </p>
            <div style={{ marginTop: 'auto', paddingTop: 16, fontSize: '0.8rem', fontWeight: 700, color: 'var(--lp-blue)' }}>
              ✓ Switch anytime
            </div>
          </div>
        </div>
      </section>

      {/* 5. Hosting & Pricing Options */}
      <section className="piko-section" id="hosting-options" style={{ background: 'rgba(255, 255, 255, 0.45)', borderRadius: 36 }}>
        <div className="piko-section-header">
          <span className="piko-section-tag">Your Family · Your Choice</span>
          <h2 className="piko-section-title">Two ways to use Piko. Both first-class.</h2>
          <p className="piko-section-desc">
            Family safety that fits the way you live. Let us handle the setup, or run Piko on your own terms.
          </p>
        </div>

        <div className="piko-pricing-grid">
          {/* Card 1: Piko Hosted */}
          <div className="piko-pricing-card featured">
            <span className="piko-featured-badge">Recommended for Families</span>
            <div style={{ fontSize: '0.75rem', fontWeight: 800, textTransform: 'uppercase', color: 'var(--lp-primary)', letterSpacing: '0.05em' }}>
              Option A · Hosted Subscription
            </div>
            <h3 style={{ fontSize: '1.75rem', fontWeight: 800, margin: '8px 0 4px 0', color: 'var(--lp-text)' }}>
              Piko Hosted
            </h3>
            <p style={{ fontSize: '0.925rem', color: 'var(--lp-muted)', marginBottom: 12 }}>
              Zero server administration. High-availability cloud, automatic security patches, and instant onboarding.
            </p>

            {/* Pricing Tag */}
            <div className="piko-price-tag">
              <span className="piko-price-amount">₹300</span>
              <span className="piko-price-period">/ family / month</span>
            </div>

            <ul className="piko-feature-list">
              <li className="piko-feature-item">
                <span className="piko-feature-check">✓</span>
                <span>Fully managed cloud infrastructure &amp; automatic upgrades</span>
              </li>
              <li className="piko-feature-item">
                <span className="piko-feature-check">✓</span>
                <span>Zero server setup, database configuration, or maintenance</span>
              </li>
              <li className="piko-feature-item">
                <span className="piko-feature-check">✓</span>
                <span>Instant Android device pairing via authenticated QR codes</span>
              </li>
              <li className="piko-feature-item">
                <span className="piko-feature-check">✓</span>
                <span>Pre-configured push notifications &amp; priority battery alerts</span>
              </li>
              <li className="piko-feature-item">
                <span className="piko-feature-check">✓</span>
                <span>Redundant point-in-time telemetry backups</span>
              </li>
              <li className="piko-feature-item">
                <span className="piko-feature-check">✓</span>
                <span>Transparent subscription billing (cancel anytime in 1 click)</span>
              </li>
            </ul>

            <Link to="/login" className="piko-btn-primary" style={{ width: '100%', padding: '14px' }}>
              <span>Get started with hosted Piko</span>
              <span aria-hidden="true">→</span>
            </Link>
            <p style={{ textAlign: 'center', fontSize: '0.75rem', color: 'var(--lp-muted)', marginTop: 10 }}>
              Ready in under 2 minutes · No lock-in
            </p>
          </div>

          {/* Card 2: Self-Hosted Piko */}
          <div className="piko-pricing-card" id="self-hosting">
            <div style={{ fontSize: '0.75rem', fontWeight: 800, textTransform: 'uppercase', color: 'var(--lp-muted)', letterSpacing: '0.05em' }}>
              Option B · Self-Hosted Sovereignty
            </div>
            <h3 style={{ fontSize: '1.75rem', fontWeight: 800, margin: '8px 0 4px 0', color: 'var(--lp-text)' }}>
              Self-Hosted Piko
            </h3>
            <p style={{ fontSize: '0.925rem', color: 'var(--lp-muted)', marginBottom: 12 }}>
              For technically confident families, homelab hobbyists, and privacy maximalists wanting complete custody.
            </p>

            {/* Pricing Tag */}
            <div className="piko-price-tag">
              <span className="piko-price-amount">Free</span>
              <span className="piko-price-period">Open Source (AGPL-3.0)</span>
            </div>

            <ul className="piko-feature-list">
              <li className="piko-feature-item">
                <span className="piko-feature-check">✓</span>
                <span>Run your own server via Docker Compose on local hardware or VPS</span>
              </li>
              <li className="piko-feature-item">
                <span className="piko-feature-check">✓</span>
                <span>100% data sovereignty: coordinates &amp; telemetry stay on your disks</span>
              </li>
              <li className="piko-feature-item">
                <span className="piko-feature-check">✓</span>
                <span>Full API parity with native Android apps</span>
              </li>
              <li className="piko-feature-item">
                <span className="piko-feature-check">✓</span>
                <span>Custom retention schedules &amp; database pruning</span>
              </li>
              <li className="piko-feature-item">
                <span className="piko-feature-check" style={{ background: 'var(--lp-softblue)', color: 'var(--lp-blue)' }}>ℹ</span>
                <span>Requires server administration, SSL, and DNS maintenance</span>
              </li>
              <li className="piko-feature-item">
                <span className="piko-feature-check" style={{ background: 'var(--lp-softblue)', color: 'var(--lp-blue)' }}>ℹ</span>
                <span>Bring your own push notification &amp; map tile credentials</span>
              </li>
            </ul>

            <Link to="/login" className="piko-btn-secondary" style={{ width: '100%', padding: '14px' }}>
              <span>Launch your self-hosted setup</span>
              <span aria-hidden="true">→</span>
            </Link>
            <p style={{ textAlign: 'center', fontSize: '0.75rem', color: 'var(--lp-muted)', marginTop: 10 }}>
              Docker ready · Full documentation included
            </p>
          </div>
        </div>

        {/* 6. Comparison Feature Matrix */}
        <div className="piko-matrix-wrapper" id="matrix">
          <div style={{ marginBottom: 16 }}>
            <h3 style={{ fontSize: '1.25rem', fontWeight: 800, color: 'var(--lp-text)' }}>Architecture Comparison</h3>
            <p style={{ fontSize: '0.85rem', color: 'var(--lp-muted)' }}>Side-by-side technical breakdown</p>
          </div>

          <table className="piko-matrix-table">
            <thead>
              <tr>
                <th>Capability</th>
                <th>Piko Hosted (₹300/mo)</th>
                <th>Self-Hosted Piko (Free)</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><strong>Setup Duration</strong></td>
                <td>Under 2 minutes via QR scan</td>
                <td>~15 minutes (Docker Compose)</td>
              </tr>
              <tr>
                <td><strong>Data Custody</strong></td>
                <td>Dedicated tenant, encrypted at rest</td>
                <td>100% on your personal hardware</td>
              </tr>
              <tr>
                <td><strong>Server Administration</strong></td>
                <td>Zero (managed by Piko team)</td>
                <td>Operator handles updates &amp; SSL</td>
              </tr>
              <tr>
                <td><strong>Push Relays</strong></td>
                <td>Pre-configured high-priority relays</td>
                <td>Bring your own FCM / APNS keys</td>
              </tr>
              <tr>
                <td><strong>Automated Backups</strong></td>
                <td>Multi-region managed snapshots</td>
                <td>Self-managed volume backups</td>
              </tr>
              <tr>
                <td><strong>Mobile App Parity</strong></td>
                <td>Native Android (Material 3)</td>
                <td>Native Android (point to your domain)</td>
              </tr>
              <tr>
                <td><strong>Pricing</strong></td>
                <td><strong>₹300 / family / month</strong></td>
                <td><strong>Free &amp; Open Source</strong></td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      {/* 7. Feature Showcase */}
      <section className="piko-section" id="features">
        <div className="piko-section-header">
          <span className="piko-section-tag">Thoughtful Craft</span>
          <h2 className="piko-section-title">Real features built for real families</h2>
          <p className="piko-section-desc">
            Every tool is designed to be gentle, battery-conscious, and honest about network realities.
          </p>
        </div>

        <div className="piko-bento-grid">
          {/* Feature 1: Live Family Map */}
          <div className="piko-clay-card piko-bento-col-8">
            <span style={{ fontSize: '0.75rem', fontWeight: 800, textTransform: 'uppercase', color: 'var(--lp-blue)' }}>
              Live &amp; Geofenced
            </span>
            <h3 className="piko-card-title">Live Family Map &amp; Safe Zones</h3>
            <p className="piko-card-desc">
              Real-time spatial awareness with circular precision uncertainty (±5m), arrival safe-zone notifications, and transparent freshness indicators. Never guess if data is stale.
            </p>

            <div className="piko-mockup-well">
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem', fontWeight: 700, marginBottom: 10 }}>
                <span>Bengaluru Safe Corridor · 2 Active Nodes</span>
                <span style={{ color: 'var(--lp-muted)' }}>Updated 18s ago</span>
              </div>
              <div style={{ height: 80, borderRadius: 14, background: 'linear-gradient(90deg, #e7f0fd, #f3eeff, #e4f5eb)', display: 'flex', alignItems: 'center', justifyContent: 'space-around', padding: '0 12px' }}>
                <span style={{ background: '#fff', padding: '6px 12px', borderRadius: 10, fontSize: '0.75rem', fontWeight: 700, boxShadow: '0 2px 6px rgba(0,0,0,0.06)' }}>
                  🔵 Aarav · School (Gate 2)
                </span>
                <span style={{ background: '#fff', padding: '6px 12px', borderRadius: 10, fontSize: '0.75rem', fontWeight: 700, boxShadow: '0 2px 6px rgba(0,0,0,0.06)' }}>
                  🟢 Diya · Art Studio
                </span>
              </div>
            </div>
          </div>

          {/* Feature 2: Battery Health */}
          <div className="piko-clay-card piko-bento-col-4">
            <span style={{ fontSize: '0.75rem', fontWeight: 800, textTransform: 'uppercase', color: 'var(--lp-primary)' }}>
              Telemetry Health
            </span>
            <h3 className="piko-card-title">Device Battery &amp; Health</h3>
            <p className="piko-card-desc">
              Track battery percentage, fast charging status, and network connection without pinging your child repeatedly.
            </p>
            <div className="piko-mockup-well" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div>
                <div style={{ fontSize: '1.75rem', fontWeight: 900, color: 'var(--lp-text)' }}>84%</div>
                <div style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--lp-mint-dark)' }}>Fast Charging</div>
              </div>
              <span style={{ background: 'var(--lp-softblue)', color: 'var(--lp-blue)', padding: '4px 10px', borderRadius: 8, fontSize: '0.75rem', fontWeight: 700 }}>
                5G Active
              </span>
            </div>
          </div>

          {/* Feature 3: Urgent SOS */}
          <div className="piko-clay-card piko-bento-col-4">
            <span style={{ fontSize: '0.75rem', fontWeight: 800, textTransform: 'uppercase', color: 'var(--lp-critical)' }}>
              Emergency Triage
            </span>
            <h3 className="piko-card-title">Instant Emergency SOS</h3>
            <p className="piko-card-desc">
              A 3-second hold trigger guards against accidental taps while ensuring rapid alert delivery and siren activation when it counts.
            </p>
            <div className="piko-mockup-well" style={{ background: '#fdf2f2', border: '1px solid #fed7d7', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ width: 10, height: 10, borderRadius: '50%', background: 'var(--lp-critical)' }} />
                <span style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--lp-critical)' }}>Priority Link Ready</span>
              </div>
              <span style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--lp-muted)' }}>Hold 3s</span>
            </div>
          </div>

          {/* Feature 4: Reassurance Messaging */}
          <div className="piko-clay-card piko-bento-col-8">
            <span style={{ fontSize: '0.75rem', fontWeight: 800, textTransform: 'uppercase', color: 'var(--lp-mint-dark)' }}>
              Gentle Intercom
            </span>
            <h3 className="piko-card-title">Reassurance Intercom &amp; Quick Check-Ins</h3>
            <p className="piko-card-desc">
              Pre-configured tactile check-ins like "I'm okay" or "At soccer practice" make communication seamless without typing long messages.
            </p>
            <div className="piko-mockup-well" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
              <div style={{ background: '#fff', padding: 10, borderRadius: 12, textAlign: 'center', fontSize: '0.8rem', fontWeight: 700 }}>
                👋 I'm Okay
              </div>
              <div style={{ background: '#fff', padding: 10, borderRadius: 12, textAlign: 'center', fontSize: '0.8rem', fontWeight: 700 }}>
                🏫 At School
              </div>
              <div style={{ background: '#fff', padding: 10, borderRadius: 12, textAlign: 'center', fontSize: '0.8rem', fontWeight: 700 }}>
                🚗 Heading Home
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* 8. Privacy & Family-First Pledge */}
      <section className="piko-section" id="privacy">
        <div className="piko-clay-card" style={{ padding: '48px 40px', textAlign: 'center' }}>
          <div className="piko-landing-brand-logo" style={{ margin: '0 auto 16px auto', width: 48, height: 48 }}>
            <img src={MASCOT_URL} alt="Piko logo" />
          </div>
          <h2 style={{ fontSize: '2.25rem', fontWeight: 800, marginBottom: 12, color: 'var(--lp-text)' }}>
            Built around families, not fear.
          </h2>
          <p style={{ fontSize: '1.05rem', color: 'var(--lp-muted)', maxWidth: 640, margin: '0 auto 36px auto', lineHeight: 1.6 }}>
            Piko is engineered on mutual respect. We do not sell location data, build advertising profiles, or hide location-sharing indicators from children. Whether managed in our cloud or on your own server, your family's data belongs to your family.
          </p>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 20, textAlign: 'left' }}>
            <div style={{ background: 'rgba(255,255,255,0.8)', padding: 20, borderRadius: 18, border: '1px solid var(--lp-border)' }}>
              <div style={{ fontSize: '0.75rem', fontWeight: 800, color: 'var(--lp-mint-dark)', marginBottom: 4 }}>01</div>
              <h3 style={{ fontSize: '1rem', fontWeight: 700, marginBottom: 6 }}>Open Mutual Visibility</h3>
              <p style={{ fontSize: '0.85rem', color: 'var(--lp-muted)', margin: 0 }}>Children can always see who can view their location and what permissions are active.</p>
            </div>

            <div style={{ background: 'rgba(255,255,255,0.8)', padding: 20, borderRadius: 18, border: '1px solid var(--lp-border)' }}>
              <div style={{ fontSize: '0.75rem', fontWeight: 800, color: 'var(--lp-blue)', marginBottom: 4 }}>02</div>
              <h3 style={{ fontSize: '1rem', fontWeight: 700, marginBottom: 6 }}>Zero Advertising Brokers</h3>
              <p style={{ fontSize: '0.85rem', color: 'var(--lp-muted)', margin: 0 }}>We do not monetize your movements. Our revenue comes directly from honest software subscriptions.</p>
            </div>

            <div style={{ background: 'rgba(255,255,255,0.8)', padding: 20, borderRadius: 18, border: '1px solid var(--lp-border)' }}>
              <div style={{ fontSize: '0.75rem', fontWeight: 800, color: 'var(--lp-primary)', marginBottom: 4 }}>03</div>
              <h3 style={{ fontSize: '1rem', fontWeight: 700, marginBottom: 6 }}>Self-Hosting Sovereignty</h3>
              <p style={{ fontSize: '0.85rem', color: 'var(--lp-muted)', margin: 0 }}>Want zero third-party touchpoints? Self-host the backend in Docker on your own local server.</p>
            </div>
          </div>
        </div>
      </section>

      {/* 9. FAQ Accordion */}
      <section className="piko-section" id="faq">
        <div className="piko-section-header">
          <span className="piko-section-tag">Questions &amp; Answers</span>
          <h2 className="piko-section-title">Frequently asked questions</h2>
          <p className="piko-section-desc">Clear, honest answers about Piko, hosting differences, and platform support.</p>
        </div>

        <div className="piko-faq-list">
          <details className="piko-faq-item">
            <summary className="piko-faq-summary">
              <span>What is Piko?</span>
              <span className="piko-faq-arrow">▼</span>
            </summary>
            <div className="piko-faq-content">
              Piko is a modern personal security and family connectivity product. It provides parents and children with shared location, accuracy indicators, battery health telemetry, historical activity, emergency SOS triggers, and reassurance check-ins.
            </div>
          </details>

          <details className="piko-faq-item">
            <summary className="piko-faq-summary">
              <span>What is the difference between Piko Hosted and Self-Hosted?</span>
              <span className="piko-faq-arrow">▼</span>
            </summary>
            <div className="piko-faq-content">
              With <strong>Piko Hosted</strong>, our team manages the cloud server, database, automatic upgrades, and high availability for ₹300/family/month. With <strong>Self-Hosted Piko</strong>, you deploy the software on your own server or home hardware for free, retaining full physical custody over your data.
            </div>
          </details>

          <details className="piko-faq-item">
            <summary className="piko-faq-summary">
              <span>How much does Piko Hosted cost?</span>
              <span className="piko-faq-arrow">▼</span>
            </summary>
            <div className="piko-faq-content">
              Piko Hosted is <strong>300 INR / family / month</strong> (₹300/mo). This covers your entire household with unlimited family members and devices, high-availability hosting, automated backups, and push notification relays.
            </div>
          </details>

          <details className="piko-faq-item">
            <summary className="piko-faq-summary">
              <span>Do I need technical expertise to self-host Piko?</span>
              <span className="piko-faq-arrow">▼</span>
            </summary>
            <div className="piko-faq-content">
              Yes, self-hosting requires familiarity with Docker, reverse proxies, and server maintenance. You will also manage your own backups and system updates. If you prefer zero maintenance, Piko Hosted is ready instantly.
            </div>
          </details>

          <details className="piko-faq-item">
            <summary className="piko-faq-summary">
              <span>Can I migrate between Hosted and Self-Hosted later?</span>
              <span className="piko-faq-arrow">▼</span>
            </summary>
            <div className="piko-faq-content">
              Yes. Piko uses standardized family export formats so you can take your family configuration and telemetry history with you if you decide to switch hosting models.
            </div>
          </details>

          <details className="piko-faq-item">
            <summary className="piko-faq-summary">
              <span>Does Piko work on Android phones?</span>
              <span className="piko-faq-arrow">▼</span>
            </summary>
            <div className="piko-faq-content">
              Yes, Piko is natively optimized for Android with Material 3 foundations, battery guardrails, offline store-and-forward syncing, and emergency SOS triggers.
            </div>
          </details>
        </div>
      </section>

      {/* 10. Final Call to Action */}
      <section className="piko-section" style={{ paddingTop: 20 }}>
        <div className="piko-cta-banner">
          <h2 style={{ fontSize: '2.5rem', fontWeight: 800, marginBottom: 12, color: 'var(--lp-text)' }}>
            Find your family's way to Piko.
          </h2>
          <p style={{ fontSize: '1.15rem', color: 'var(--lp-muted)', maxWidth: 540, margin: '0 auto 32px auto' }}>
            Choose the convenience of hosted Piko (₹300/mo) or the complete control of running it yourself.
          </p>

          <div style={{ display: 'flex', gap: 16, justifyContent: 'center', flexWrap: 'wrap' }}>
            <Link to="/login" className="piko-btn-primary" style={{ padding: '16px 32px', fontSize: '1.05rem' }}>
              <span>Get started with hosted Piko</span>
              <span aria-hidden="true">→</span>
            </Link>
            <a href="#hosting-options" className="piko-btn-secondary" style={{ padding: '16px 28px', fontSize: '1.05rem' }}>
              <span>Compare hosting options</span>
            </a>
          </div>
        </div>
      </section>

      {/* 11. Footer */}
      <footer className="piko-landing-footer">
        <div className="piko-footer-inner">
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div className="piko-landing-brand-logo" style={{ width: 32, height: 32 }}>
              <img src={MASCOT_URL} alt="Piko icon" />
            </div>
            <span style={{ fontWeight: 800, color: 'var(--lp-text)' }}>Piko</span>
            <span style={{ fontSize: '0.75rem', color: 'var(--lp-muted)' }}>· Connected by care. Protected by choice.</span>
          </div>

          <div className="piko-footer-links">
            <a href="#features">Features</a>
            <a href="#how-it-works">How it works</a>
            <a href="#hosting-options">Pricing</a>
            <a href="#privacy">Privacy</a>
            <a href="#faq">FAQ</a>
            <Link to="/login">Sign in</Link>
          </div>
        </div>
      </footer>
    </div>
  )
}
