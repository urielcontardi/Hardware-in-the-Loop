#ifndef PWM_EVENTS_H
#define PWM_EVENTS_H

#include <stdint.h>

#define PWM_EVENTS_PORT 5007
#define PWM_EVENTS_CLOCK_HZ 100000000U

int  pwm_events_init(const char *dest_ip);
void pwm_events_start(void);
void pwm_events_stop(void);
void pwm_events_poll(void);
void pwm_events_deinit(void);

#endif /* PWM_EVENTS_H */
