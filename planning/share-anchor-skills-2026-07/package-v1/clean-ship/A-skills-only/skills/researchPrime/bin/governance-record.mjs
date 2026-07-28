// bin/governance-record.mjs — Wave 3 Canonical governance record schema + shared validator
import crypto from 'node:crypto';

export const SCHEMA_VERSION = 1;

/**
 * Deterministic JSON stringify (sorts keys recursively for stable hashing).
 * Shared with formal-governor but duplicated/imported here for completeness.
 */
function deterministicStringify(obj) {
  if (obj === null || typeof obj !== 'object') {
    return JSON.stringify(obj);
  }
  if (Array.isArray(obj)) {
    return '[' + obj.map(deterministicStringify).join(',') + ']';
  }
  const keys = Object.keys(obj).sort();
  const parts = keys.map(k => JSON.stringify(k) + ':' + deterministicStringify(obj[k]));
  return '{' + parts.join(',') + '}';
}

/**
 * Canonicalizes a governance record string:
 * - Parses it (handling unexpected whitespace/CRLF).
 * - Re-serializes it with stable key order.
 * - Distinguishes between unparseable/unsafe (throws) and unexpected-but-safe (warns).
 * 
 * @param {string} recordStr The raw JSON string
 * @returns {object} { canonicalString, parsedObject, warnings }
 */
export function canonicalizeRecord(recordStr) {
  let parsed;
  try {
    parsed = JSON.parse(recordStr);
  } catch (e) {
    throw new Error('HALT: Unparseable governance record: ' + e.message);
  }

  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    throw new Error('HALT: Unsafe governance record: must be a JSON object');
  }

  const warnings = [];
  
  // Enforce common core keys exist
  const coreKeys = [
    'schema_version',
    'skill_name',
    'triage_artifact_hash',
    'gate_1_decision',
    'plan_artifact_hash',
    'gate_2_decision',
    'locked_governor_output',
    'locked_governor_hash',
    'host_approval_provider'
  ];

  for (const key of Object.keys(parsed)) {
    if (!coreKeys.includes(key) && !key.startsWith('ext_')) {
      warnings.push(`Unexpected-but-safe: unknown optional field '${key}'`);
    }
  }

  const canonicalString = deterministicStringify(parsed);
  return { canonicalString, parsedObject: parsed, warnings };
}

const extensionValidators = new Map();

export function registerExtensionValidator(skillName, validatorFn) {
  extensionValidators.set(skillName, validatorFn);
}

/**
 * Validates a governance record object against the core schema and its registered skill extension.
 * @param {object} record The canonicalized governance record object.
 * @returns {object} { valid: boolean, errors: array }
 */
export function validateGovernanceRecord(record) {
  const errors = [];
  
  if (record.schema_version !== SCHEMA_VERSION) {
    errors.push(`Invalid schema_version: expected ${SCHEMA_VERSION}, got ${record.schema_version}`);
  }
  
  if (!record.skill_name || typeof record.skill_name !== 'string') {
    errors.push('Missing or invalid skill_name');
  }
  
  if (!record.triage_artifact_hash || typeof record.triage_artifact_hash !== 'string') {
    errors.push('Missing or invalid triage_artifact_hash');
  }
  
  if (!['APPROVE', 'EDIT', 'ABORT'].includes(record.gate_1_decision)) {
    errors.push(`Invalid gate_1_decision: ${record.gate_1_decision}`);
  }
  
  if (!record.plan_artifact_hash || typeof record.plan_artifact_hash !== 'string') {
    errors.push('Missing or invalid plan_artifact_hash');
  }
  
  if (!['APPROVE', 'EDIT', 'ABORT'].includes(record.gate_2_decision)) {
    errors.push(`Invalid gate_2_decision: ${record.gate_2_decision}`);
  }
  
  if (!record.locked_governor_output || typeof record.locked_governor_output !== 'object') {
    errors.push('Missing or invalid locked_governor_output');
  }
  
  if (!record.locked_governor_hash || typeof record.locked_governor_hash !== 'string') {
    errors.push('Missing or invalid locked_governor_hash');
  } else {
    // Validate the hash binding
    const expectedHash = crypto.createHash('sha256').update(deterministicStringify(record.locked_governor_output)).digest('hex');
    if (record.locked_governor_hash !== expectedHash) {
      errors.push(`locked_governor_hash mismatch. Expected ${expectedHash}, got ${record.locked_governor_hash}`);
    }
  }

  // Allow empty host_approval_provider but require string if present
  if (record.host_approval_provider !== undefined && typeof record.host_approval_provider !== 'string') {
    errors.push('Invalid host_approval_provider');
  }

  // Dispatch to per-skill extension validator
  if (record.skill_name) {
    const extValidator = extensionValidators.get(record.skill_name);
    if (extValidator) {
      const extErrors = extValidator(record);
      if (extErrors && extErrors.length > 0) {
        errors.push(...extErrors.map(e => `[${record.skill_name} extension] ${e}`));
      }
    } else {
      // Missing extension validator is an error if skill is specified but not registered?
      // For forward compatibility, maybe we just warn, but tests usually want strictness for known skills.
      // We will only validate if registered.
    }
  }

  return {
    valid: errors.length === 0,
    errors
  };
}

/**
 * researchPrime per-skill extension validator
 */
export function researchPrimeExtensionValidator(record) {
  const errors = [];
  // researchPrime might require specific fields, e.g., ext_research_target
  if (!record.ext_research_target || typeof record.ext_research_target !== 'string') {
    errors.push('Missing or invalid ext_research_target');
  }
  return errors;
}

// Register the researchPrime extension by default
registerExtensionValidator('researchPrime', researchPrimeExtensionValidator);
