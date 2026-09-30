/* foc.h - field-oriented control transforms and space-vector PWM.
 * Pure C, single-precision float, no register access.
 *
 * Conventions:
 * - Clarke is amplitude-invariant: alpha = a, beta = (a + 2b)/sqrt(3),
 *   assuming a + b + c = 0.
 * - Park rotates by the electrical angle theta, passed as sin/cos so a caller
 *   computes them once: d = alpha*cos + beta*sin, q = -alpha*sin + beta*cos.
 * - SVPWM is min-max (common-mode) injection. Duty 0.5 is the centre: the zero
 *   vector gives 0.5 on every phase. duty_x = 0.5 + (v_x + v_off)/vbus with
 *   v_off = -(max + min)/2, clamped to 0..max_duty. The linear range is
 *   |v| <= vbus/sqrt(3). vbus <= 0 yields the zero vector (0.5, clamped). */
#ifndef FOC_H
#define FOC_H

#define FOC_SQRT3 1.7320508f
#define FOC_INV_SQRT3 0.57735027f

typedef struct { float a, b, c; } foc_abc_t;
typedef struct { float alpha, beta; } foc_ab_t;
typedef struct { float d, q; } foc_dq_t;

foc_ab_t foc_clarke(float a, float b);
foc_abc_t foc_inv_clarke(foc_ab_t v);
foc_dq_t foc_park(foc_ab_t v, float sin_t, float cos_t);
foc_ab_t foc_inv_park(foc_dq_t v, float sin_t, float cos_t);
foc_abc_t foc_svpwm(foc_ab_t v, float vbus, float max_duty);

#endif
