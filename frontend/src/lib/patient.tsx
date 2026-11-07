'use client';
import { createContext, useContext } from 'react';
import type { Patient } from './types';
export const PatientContext = createContext<{patient: Patient; reload: () => Promise<void>} | null>(null);
export function usePatient() {
  const context = useContext(PatientContext);
  if (!context) throw new Error('Patient context is required.');
  return context;
}
