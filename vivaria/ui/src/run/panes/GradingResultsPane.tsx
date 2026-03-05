import { InfoCircleFilled, CheckCircleFilled, CloseCircleFilled } from '@ant-design/icons'
import { Card, Spin, Tag, Typography } from 'antd'
import { useEffect, useState } from 'react'
import { trpc } from '../../../trpc'

const { Text, Paragraph, Title } = Typography

export function GradingResultsPane({ runId }: { runId: number }) {
  const [gradingResult, setGradingResult] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    // Fetch run metadata to get grading results
    const fetchGradingResult = async () => {
      try {
        const runData = await trpc.getRun.query({ runId })
        if (runData?.metadata?.grading) {
          setGradingResult(runData.metadata.grading)
        }
      } catch (error) {
        console.error('Failed to fetch grading results:', error)
      } finally {
        setLoading(false)
      }
    }

    fetchGradingResult()
    // Poll every 10 seconds for updates
    const interval = setInterval(fetchGradingResult, 10000)

    return () => clearInterval(interval)
  }, [runId])

  if (loading) {
    return (
      <div style={{ padding: '24px', textAlign: 'center' }}>
        <Spin size="large" />
        <Paragraph style={{ marginTop: '16px' }}>Loading grading results...</Paragraph>
      </div>
    )
  }

  if (!gradingResult) {
    return (
      <div style={{ padding: '24px', textAlign: 'center' }}>
        <InfoCircleFilled style={{ fontSize: '48px', color: '#888' }} />
        <Title level={4} style={{ marginTop: '16px', color: '#888' }}>
          No Grading Results Available
        </Title>
        <Paragraph type="secondary">
          Grading will be performed automatically after the agent submits a solution.
        </Paragraph>
      </div>
    )
  }

  const isPassing = gradingResult.result === 'PASS'
  const icon = isPassing ? (
    <CheckCircleFilled style={{ fontSize: '32px', color: '#52c41a' }} />
  ) : (
    <CloseCircleFilled style={{ fontSize: '32px', color: '#f5222d' }} />
  )

  const tagColor = isPassing ? 'success' : 'error'

  return (
    <div style={{ padding: '24px' }}>
      <Card>
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px', marginBottom: '24px' }}>
          {icon}
          <div style={{ flex: 1 }}>
            <Title level={3} style={{ margin: 0 }}>
              Grading Result
            </Title>
            <Tag color={tagColor} style={{ marginTop: '8px' }}>
              {gradingResult.result}
            </Tag>
          </div>
          <div style={{ textAlign: 'right' }}>
            <Text type="secondary">Graded at</Text>
            <br />
            <Text>{new Date(gradingResult.gradedAt).toLocaleString()}</Text>
          </div>
        </div>

        <div style={{ marginTop: '24px' }}>
          <Title level={5}>Reasoning</Title>
          <Card type="inner" style={{ backgroundColor: '#f5f5f5' }}>
            <Paragraph style={{ whiteSpace: 'pre-wrap', margin: 0 }}>
              {gradingResult.reasoning || 'No reasoning provided'}
            </Paragraph>
          </Card>
        </div>

        {gradingResult.statistics && (
          <div style={{ marginTop: '24px' }}>
            <Title level={5}>Statistics</Title>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '16px' }}>
              {Object.entries(gradingResult.statistics).map(([key, value]) => (
                <div key={key}>
                  <Text type="secondary">{key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}:</Text>
                  <br />
                  <Text strong>{typeof value === 'number' ? value.toLocaleString() : String(value)}</Text>
                </div>
              ))}
            </div>
          </div>
        )}
      </Card>
    </div>
  )
}