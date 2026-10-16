package app.piko.android.core

class InMemoryEventStoreContractTest : EventStoreContract() {
    override fun newStore(capacity: Int): EventStore = InMemoryEventStore(capacity)
}
