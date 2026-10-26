import { useState } from 'react'

// Placeholder until billing exists: checked in the browser only, so it is not a secret and grants nothing by itself.
const EARLY_BIRD_CODE = 'EARLYBIRDOFF3R'

/** Accepts the early-bird code and says plainly that nothing is charged or activated yet. */
export function CouponBox({ id }: { id: string }) {
  const [coupon, setCoupon] = useState('')
  const [state, setState] = useState<'idle' | 'applied' | 'invalid'>('idle')
  return (
    <form
      className="piko-coupon"
      onSubmit={(e) => {
        e.preventDefault()
        setState(coupon.trim().toUpperCase() === EARLY_BIRD_CODE ? 'applied' : 'invalid')
      }}
    >
      <label htmlFor={`${id}-input`}>Have a coupon code?</label>
      <div className="piko-coupon-row">
        <input
          id={`${id}-input`}
          value={coupon}
          onChange={(e) => {
            setCoupon(e.target.value)
            setState('idle')
          }}
          autoComplete="off"
          autoCapitalize="characters"
          spellCheck={false}
          aria-describedby={`${id}-status`}
        />
        <button type="submit" className="piko-btn-secondary" disabled={!coupon.trim()}>
          Apply
        </button>
      </div>
      <p id={`${id}-status`} role="status" className={`piko-coupon-status ${state}`}>
        {state === 'applied' &&
          'Early-bird code applied: your first month of Piko Hosted is free. Online signup and billing are not open yet, so nothing is charged or activated today.'}
        {state === 'invalid' && 'That code is not valid. Check it and try again.'}
      </p>
    </form>
  )
}
