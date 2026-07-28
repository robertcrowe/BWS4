// Built with Spec4 AI - https://spec4.ai
import { useHealthQuery } from '../../api/useHealth'

/**
 * Minimal root screen that calls the backend health check on load and
 * displays a connected or error state.
 */
export function HealthScreen() {
  const { data, isPending, isError } = useHealthQuery()

  if (isPending) {
    return <p className="p-8 text-center text-lg text-gray-500">Checking backend...</p>
  }

  if (isError || data?.status !== 'ok') {
    return (
      <p role="alert" className="p-8 text-center text-lg text-red-600 dark:text-red-400">
        Backend: error
      </p>
    )
  }

  return (
    <p className="p-8 text-center text-lg text-green-600 dark:text-green-400">Backend: connected</p>
  )
}
