package app.piko.android.comms

import android.app.job.JobParameters
import android.app.job.JobService
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Runs when the system has a network and the outbox has something in it. Returning "reschedule"
 * makes the system retry with exponential backoff, so a queued SOS keeps being retried even if the
 * app process was killed. No location is collected here; this only delivers what the user already
 * chose to send.
 */
class OutboxJobService : JobService() {
    private val stopped = AtomicBoolean(false)

    override fun onStartJob(params: JobParameters): Boolean {
        stopped.set(false)
        Thread {
            val more = try {
                CommsRunner.runOnce(applicationContext)
            } catch (_: Exception) {
                true // unexpected failure: let the system retry; the item is still on disk
            }
            jobFinished(params, more && !stopped.get())
        }.start()
        return true
    }

    override fun onStopJob(params: JobParameters): Boolean {
        stopped.set(true)
        return true // the system stopped us (for example the network went away): run again later
    }
}
