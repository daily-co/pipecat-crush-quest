/**
 * Vercel serverless function to proxy requests to Pipecat Cloud
 * Keeps the API key secret on the server side
 */

export default async function handler(req, res) {
  // Only allow POST
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  // CORS headers
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    return res.status(200).end();
  }

  const { to_number, from_number } = req.body;

  // Get API key from environment variable (set in Vercel dashboard)
  const apiKey = process.env.PIPECAT_API_KEY;
  if (!apiKey) {
    console.error('PIPECAT_API_KEY not configured');
    return res.status(500).json({ error: 'Server configuration error' });
  }

  // Pipecat Cloud agent URL
  const agentUrl = process.env.PIPECAT_AGENT_URL || 'https://api.pipecat.daily.co/v1/public/crush-quest';

  try {
    const response = await fetch(`${agentUrl}/start`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${apiKey}`,
      },
      body: JSON.stringify({
        createDailyRoom: true,
        body: {
          to_number: to_number || '+13373338444',
          from_number: from_number || '+15550000000',
        },
      }),
    });

    if (!response.ok) {
      const error = await response.text();
      console.error('Pipecat Cloud error:', error);
      return res.status(response.status).json({ error: 'Failed to start session' });
    }

    const data = await response.json();
    
    // Return Daily room info to frontend
    return res.status(200).json({
      room_url: data.dailyRoom,
      token: data.dailyToken,
    });
  } catch (error) {
    console.error('Error calling Pipecat Cloud:', error);
    return res.status(500).json({ error: 'Failed to connect to bot service' });
  }
}
