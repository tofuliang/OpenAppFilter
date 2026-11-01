// SPDX-License-Identifier: GPL-2.0-or-later
#ifndef __FWX_TRAFFIC_H__
#define __FWX_TRAFFIC_H__

/* Initialize before packet hooks; exit after hooks and maintenance are drained.
 * An immutable staged batch remains until userspace commits it and sends an
 * exact boot_id/seq ACK; shutdown still cannot promise persistence of RAM. */
void af_traffic_v2_init(void);
void af_traffic_v2_exit(void);
void af_traffic_v2_record(const unsigned char *mac, unsigned int app_id,
			  int pkt_dir, unsigned int bytes);
void af_traffic_v2_unattributed(int pkt_dir, unsigned int bytes);
void af_traffic_v2_report(void);
int af_traffic_v2_handle_ack(const char *data, unsigned int len);

#endif
