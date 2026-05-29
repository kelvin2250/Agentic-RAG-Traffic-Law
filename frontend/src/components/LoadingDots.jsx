import React from 'react';
import styles from './LoadingDots.module.css';

export default function LoadingDots() {
  return (
    <div className={styles.container}>
      <span className={styles.dot}></span>
      <span className={styles.dot}></span>
      <span className={styles.dot}></span>
    </div>
  );
}
