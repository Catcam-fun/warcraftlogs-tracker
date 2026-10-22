// Floor Pov circuit breaker (infra/breaker/breaker.yaml). Any message on the
// breaker topic, from a traffic alarm or the budget, stops the API Lambda
// (reserved concurrency 0) and disables the CloudFront distribution.
// Reset: GitHub Actions > "Reset breaker".
'use strict';

// Alarm messages are JSON; budget messages are plain text. Only an alarm
// going back to OK is ignored; anything else trips.
function isRecovery(message) {
  try { return JSON.parse(message).NewStateValue === 'OK'; } catch { return false; }
}

function makeHandler({ cf, lambda, distId, apiFunction, log = console.log }) {
  return async (event) => {
    const messages = (event.Records || []).map((r) => (r.Sns && r.Sns.Message) || '');
    if (messages.length && messages.every(isRecovery)) {
      log('Alarm back to OK: nothing to do.');
      return { tripped: false };
    }
    log('Tripping on: ' + messages.map((m) => m.slice(0, 300)).join(' | '));
    const errors = [];
    try {
      await lambda.putFunctionConcurrency({ FunctionName: apiFunction, ReservedConcurrentExecutions: 0 });
      log('API stopped (reserved concurrency 0).');
    } catch (e) {
      errors.push(e);
      log('Stopping the API failed: ' + e.message);
    }
    try {
      const { DistributionConfig: config, ETag } = await cf.getDistributionConfig({ Id: distId });
      if (!config.Enabled) {
        log('CloudFront already disabled.');
      } else {
        config.Enabled = false;
        await cf.updateDistribution({ Id: distId, IfMatch: ETag, DistributionConfig: config });
        log('CloudFront disabled.');
      }
    } catch (e) {
      errors.push(e);
      log('Disabling CloudFront failed: ' + e.message);
    }
    if (errors.length) throw errors[0]; // the failed delivery is retried
    return { tripped: true };
  };
}

exports.isRecovery = isRecovery;
exports.makeHandler = makeHandler;
exports.handler = (event) => {
  // The AWS SDK ships with the Lambda Node.js runtime.
  const { CloudFront } = require('@aws-sdk/client-cloudfront');
  const { Lambda } = require('@aws-sdk/client-lambda');
  return makeHandler({
    cf: new CloudFront({}),
    lambda: new Lambda({}),
    distId: process.env.DISTRIBUTION_ID,
    apiFunction: process.env.API_FUNCTION,
  })(event);
};
