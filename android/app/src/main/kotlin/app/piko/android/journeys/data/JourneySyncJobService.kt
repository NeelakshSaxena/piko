package app.piko.android.journeys.data

import android.app.job.JobParameters
import android.app.job.JobService
import java.util.concurrent.atomic.AtomicBoolean

/** Runs when a network exists and a journey backup or delete is waiting. Collects nothing. */
class JourneySyncJobService : JobService() {
    private val stopped = AtomicBoolean(false)

    override fun onStartJob(params: JobParameters): Boolean {
        stopped.set(false)
        Thread {
            val more = try {
                JourneySync.runOnce(applicationContext)
            } catch (_: Exception) {
                true // unexpected failure: the work is still on disk, let the system retry
            }
            jobFinished(params, more && !stopped.get())
        }.start()
        return true
    }

    override fun onStopJob(params: JobParameters): Boolean {
        stopped.set(true)
        return true
    }
}
