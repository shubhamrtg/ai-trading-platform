export default function DecisionFlow() {
  const stages = [
    {
      name: 'Strategy',
      description: 'Registered strategy evaluates market data and generates trading signals.',
      color: 'bg-blue-100 border-blue-400',
    },
    {
      name: 'Signal',
      description: 'A proposal specifying symbol, side, quantity, and entry price. Not yet executable.',
      color: 'bg-indigo-100 border-indigo-400',
    },
    {
      name: 'Risk Engine',
      description: 'Evaluates the signal against risk policy, position limits, exposure, and drawdown. FINAL AUTHORITY over execution.',
      color: 'bg-amber-100 border-amber-400',
    },
    {
      name: 'Risk Decision',
      description: 'APPROVED or REJECTED. If approved, specifies the authorized quantity and risk parameters.',
      color: 'bg-amber-100 border-amber-400',
    },
    {
      name: 'Order Intent',
      description: 'Risk-approved request with deterministic identity. Created only from genuinely approved decisions.',
      color: 'bg-purple-100 border-purple-400',
    },
    {
      name: 'Execution Engine',
      description: 'Verifies provenance and routes to the execution adapter. Currently simulation-only.',
      color: 'bg-green-100 border-green-400',
    },
    {
      name: 'Execution Result',
      description: 'Deterministic fill result.',
      color: 'bg-green-100 border-green-400',
    },
  ];

  return (
    <div className="bg-white rounded-lg shadow p-6">
      <h3 className="text-lg font-semibold mb-2">Architecture Overview</h3>
      <p className="text-sm text-gray-500 mb-6">
        This diagram shows the architectural pipeline that every trading decision follows.
        It is not a runtime execution record for this backtest. The UI is read-only
        and cannot initiate, modify, or override any stage.
      </p>

      <div className="space-y-3">
        {stages.map((stage, idx) => (
          <div key={stage.name}>
            <div className={`border-l-4 ${stage.color} p-4 rounded-r-lg`}>
              <h4 className="font-semibold text-gray-900">{stage.name}</h4>
              <p className="text-sm text-gray-600 mt-1">{stage.description}</p>
            </div>
            {idx < stages.length - 1 && (
              <div className="flex justify-center py-1">
                <svg className="w-5 h-5 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 14l-7 7m0 0l-7-7m7 7V3" />
                </svg>
              </div>
            )}
          </div>
        ))}
      </div>

      <div className="mt-6 p-4 bg-amber-50 border border-amber-200 rounded-lg">
        <h4 className="font-semibold text-amber-800 text-sm">Important Notes</h4>
        <ul className="mt-2 text-sm text-amber-700 list-disc list-inside space-y-1">
          <li>The Risk Engine has <strong>final authority</strong> over all trading decisions</li>
          <li>Order Intents can only be created from genuinely approved Risk Decisions</li>
          <li>The UI cannot initiate trades, override risk, or submit orders</li>
          <li>All execution is currently <strong>simulation-only</strong></li>
        </ul>
      </div>
    </div>
  );
}
