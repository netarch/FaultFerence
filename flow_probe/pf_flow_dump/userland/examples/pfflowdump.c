/*
 * (C) 2003-2019 - ntop 
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in
 * all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
 * THE SOFTWARE.
 */

#define _GNU_SOURCE
#include <signal.h>
#include <sched.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <string.h>
#include <unistd.h>
#include <sys/mman.h>
#include <errno.h>
#include <poll.h>
#include <netinet/in_systm.h>
#include <netinet/in.h>
#include <netinet/ip.h>
#include <netinet/ip6.h>
#include <net/ethernet.h>     /* the L2 protocols */
#include <sys/time.h>
#include <time.h>
#include <sys/socket.h>
#include <arpa/inet.h>
#include <monetary.h>
#include <locale.h>

#include "flow_hash.h"

#include "pfring.h"

#include "pfutils.c"

#define ALARM_SLEEP             1
#define DEFAULT_SNAPLEN      1536
#define MAX_NUM_THREADS        64
#define DEFAULT_DEVICE     "eth0"
#define NO_ZC_BUFFER_LEN     9000

pfring  *pd;
int verbose = 0, quiet = 0, num_threads = 1;
pfring_stat pfringStats;
static struct timeval startTime;
pcap_dumper_t *dumper = NULL;
u_int string_id = 1;
char *out_pcap_file = NULL;
FILE *match_dumper = NULL;
u_int8_t do_close_dump = 0, chunk_mode = 0, check_ts = 0;
u_int8_t check_seq_ip = 0, asymm_rss = 0;
int num_packets = 0;
time_t last_ts = 0;
u_int32_t last_ip = 0;
u_int16_t min_len = 0;

struct app_stats {
  u_int64_t numPkts[MAX_NUM_THREADS];
  u_int64_t numBytes[MAX_NUM_THREADS];
  u_int64_t numStringMatches[MAX_NUM_THREADS];

  volatile u_int64_t do_shutdown;
};

struct app_stats *stats;

struct strmatch {
  char *str;
  struct strmatch *next;
};

struct strmatch *matching_strings = NULL;

u_int8_t wait_for_packet = 1, do_shutdown = 0, add_drop_rule = 0;
u_int8_t use_extended_pkt_header = 0, touch_payload = 0, enable_hw_timestamp = 0, dont_strip_timestamps = 0, memcpy_test = 0;

volatile char memcpy_test_buffer[9216];

struct Ipv4TcpFlowEntry* flow_hash_map[DEFAULT_HASH_SIZE];

static void openDump();
static void dumpMatch(char *str);

/* ******************************** */

void print_stats() {
  pfring_stat pfringStat;
  struct timeval endTime;
  double deltaMillisec;
  static u_int8_t print_all;
  static u_int64_t lastPkts = 0;
  static u_int64_t lastBytes = 0;
  double diff, bytesDiff;
  static struct timeval lastTime;
  char buf[256], buf1[64], buf2[64], buf3[64], buf4[64], timebuf[128];
  u_int64_t deltaMillisecStart;

  if(startTime.tv_sec == 0) {
    gettimeofday(&startTime, NULL);
    print_all = 0;
  } else
    print_all = 1;

  gettimeofday(&endTime, NULL);
  deltaMillisec = delta_time(&endTime, &startTime);

  if(pfring_stats(pd, &pfringStat) >= 0) {
    double thpt;
    int i;
    unsigned long long nBytes = 0, nPkts = 0, nMatches = 0;

    for(i=0; i < num_threads; i++) {
      nBytes += stats->numBytes[i];
      nPkts += stats->numPkts[i];
      nMatches += stats->numStringMatches[i];
    }

    deltaMillisecStart = delta_time(&endTime, &startTime);
    snprintf(buf, sizeof(buf),
             "Duration: %s\n"
             "Packets:  %lu\n"
             "Dropped:  %lu\n"
             "Bytes:    %lu\n",
             msec2dhmsm(deltaMillisecStart, timebuf, sizeof(timebuf)),
             (long unsigned int) nPkts,
             (long unsigned int) pfringStat.drop,
             (long unsigned int) nBytes);
    pfring_set_application_stats(pd, buf);

    thpt = ((double)8*nBytes)/(deltaMillisec*1000);

    fprintf(stderr, "=========================\n"
	    "Absolute Stats: [%s pkts total][%s pkts dropped][%.1f%% dropped]\n",
	    pfring_format_numbers((double)(nPkts + pfringStat.drop), buf2, sizeof(buf2), 0),
	    pfring_format_numbers((double)(pfringStat.drop), buf3, sizeof(buf3), 0),
	    pfringStat.drop == 0 ? 0 :
	    (double)(pfringStat.drop*100)/(double)(nPkts + pfringStat.drop));
    fprintf(stderr, "[%s %s rcvd][%s bytes rcvd]",
	    pfring_format_numbers((double)nPkts, buf1, sizeof(buf1), 0),
            chunk_mode == 1 ? "chunks" : "pkts",
	    pfring_format_numbers((double)nBytes, buf2, sizeof(buf2), 0));

    if(print_all)
      fprintf(stderr, "[%s %s/sec][%s Mbit/sec]\n",
	      pfring_format_numbers((double)(nPkts*1000)/deltaMillisec, buf1, sizeof(buf1), 1),
              chunk_mode == 1 ? "chunk" : "pkt",
	      pfring_format_numbers(thpt, buf2, sizeof(buf2), 1));
    else
      fprintf(stderr, "\n");

    if(print_all && (lastTime.tv_sec > 0)) {
      deltaMillisec = delta_time(&endTime, &lastTime);
      diff = nPkts-lastPkts;
      bytesDiff = nBytes - lastBytes;
      bytesDiff /= (1000*1000*1000)/8;

      snprintf(buf, sizeof(buf),
	      "Actual Stats: [%s %s rcvd][%s ms][%s %s][%s Gbps]",
	      pfring_format_numbers(diff, buf4, sizeof(buf4), 0),
              chunk_mode == 1 ? "chunks" : "pkts",
	      pfring_format_numbers(deltaMillisec, buf1, sizeof(buf1), 1),
	      pfring_format_numbers(((double)diff/(double)(deltaMillisec/1000)),  buf2, sizeof(buf2), 1),
              chunk_mode == 1 ? "cps" : "pps",
	      pfring_format_numbers(((double)bytesDiff/(double)(deltaMillisec/1000)),  buf3, sizeof(buf3), 1));

      fprintf(stderr, "=========================\n%s\n", buf);
    }

    lastPkts = nPkts, lastBytes = nBytes;
  }

  lastTime.tv_sec = endTime.tv_sec, lastTime.tv_usec = endTime.tv_usec;

  fprintf(stderr, "=========================\n\n");
}

/* ******************************** */

void sample_filtering_rules(){
  int rc;

  if (0) {
    filtering_rule rule;

#define DUMMY_PLUGIN_ID   1

    memset(&rule, 0, sizeof(rule));

    rule.rule_id = 5;
    rule.rule_action = forward_packet_and_stop_rule_evaluation;
    rule.core_fields.proto = 6 /* tcp */;

    if((rc = pfring_add_filtering_rule(pd, &rule)) < 0)
      fprintf(stderr, "pfring_add_filtering_rule(2) failed\n");
    else if (!quiet)
      printf("Rule added successfully...\n");
  }

  if (0) {
    filtering_rule rule;

    char *sgsn = "1.2.3.4";
    char *ggsn = "1.2.3.5";

    /* ************************************* */

    memset(&rule, 0, sizeof(rule));
    rule.rule_id = 1;
    rule.rule_action = forward_packet_and_stop_rule_evaluation;
    rule.core_fields.proto = 17 /* UDP */;

    rule.core_fields.shost.v4 = ntohl(inet_addr(sgsn)),rule.core_fields.shost_mask.v4 = 0xFFFFFFFF;
    rule.core_fields.dhost.v4 = ntohl(inet_addr(ggsn)), rule.core_fields.dhost_mask.v4 = 0xFFFFFFFF;

    rule.extended_fields.tunnel.tunnel_id = 0x0000a2b6;

    if((rc = pfring_add_filtering_rule(pd, &rule)) < 0)
      fprintf(stderr, "pfring_add_filtering_rule(id=%d) failed: rc=%d\n", rule.rule_id, rc);
    else if (!quiet)
      printf("Rule %d added successfully...\n", rule.rule_id );

    /* ************************************* */

    memset(&rule, 0, sizeof(rule));

    rule.rule_id = 2;
    rule.rule_action = forward_packet_and_stop_rule_evaluation;
    rule.core_fields.proto = 17 /* UDP */;

    rule.core_fields.shost.v4 = ntohl(inet_addr(ggsn)), rule.core_fields.dhost_mask.v4 = 0xFFFFFFFF;
    rule.core_fields.dhost.v4 = ntohl(inet_addr(sgsn)), rule.core_fields.shost_mask.v4 = 0xFFFFFFFF;

    rule.extended_fields.tunnel.tunnel_id = 0x776C0000;
    if((rc = pfring_add_filtering_rule(pd, &rule)) < 0)
      fprintf(stderr, "pfring_add_filtering_rule(id=%d) failed: rc=%d\n", rule.rule_id, rc);
    else if (!quiet)
      printf("Rule %d added successfully...\n", rule.rule_id );

    /* ************************************** */

    /* Signaling (Up) */

    memset(&rule, 0, sizeof(rule));

    rule.rule_id = 3;
    rule.rule_action = forward_packet_and_stop_rule_evaluation;
    rule.core_fields.proto = 17 /* UDP */;
    rule.core_fields.sport_low = rule.core_fields.sport_high = 2123;
    rule.extended_fields.tunnel.tunnel_id = NO_TUNNEL_ID; /* Ignore the tunnel */

    if((rc = pfring_add_filtering_rule(pd, &rule)) < 0)
      fprintf(stderr, "pfring_add_filtering_rule(id=%d) failed: rc=%d\n", rule.rule_id, rc);
    else if (!quiet)
      printf("Rule %d added successfully...\n", rule.rule_id );

    memset(&rule, 0, sizeof(rule));

    /* ************************************** */

    /* Signaling (Down) */

    memset(&rule, 0, sizeof(rule));

    rule.rule_id = 4;
    rule.rule_action = forward_packet_and_stop_rule_evaluation;
    rule.core_fields.proto = 17 /* UDP */;
    rule.core_fields.dport_low = rule.core_fields.dport_high = 2123;
    rule.extended_fields.tunnel.tunnel_id = NO_TUNNEL_ID; /* Ignore the tunnel */

    if((rc = pfring_add_filtering_rule(pd, &rule)) < 0)
      fprintf(stderr, "pfring_add_filtering_rule(id=%d) failed: rc=%d\n", rule.rule_id, rc);
    else if (!quiet)
      printf("Rule %d added successfully...\n", rule.rule_id );

    memset(&rule, 0, sizeof(rule));

    /* ************************************** */

    pfring_toggle_filtering_policy(pd, 0); /* Default to drop */
  }

  if (0) { /* Accolade */
    hw_filtering_rule r = { 0 };

    r.rule_family_type = accolade_default;
    r.rule_family.accolade_rule.action = accolade_drop;

    pfring_add_hw_rule(pd, &r);

    memset(&r, 0, sizeof(r));

    r.rule_id = 0;
    r.rule_family_type = accolade_rule;
    r.rule_family.accolade_rule.action = accolade_pass;
    r.rule_family.accolade_rule.ip_version = 4;
    r.rule_family.accolade_rule.protocol = 6;
    r.rule_family.accolade_rule.src_addr.v4 = ntohl(inet_addr("10.62.4.239"));
    r.rule_family.accolade_rule.src_addr_bits = 32;
    r.rule_family.accolade_rule.src_port_low = 80;
    r.rule_family.accolade_rule.dst_addr.v4 = ntohl(inet_addr("10.62.7.8"));
    r.rule_family.accolade_rule.dst_addr_bits = 32;
    r.rule_family.accolade_rule.dst_port_low = 54830;

    if ((rc = pfring_add_hw_rule(pd, &r)) < 0)
      fprintf(stderr, "pfring_add_hw_rule(id=%d) failed: rc=%d\n", r.rule_id, rc);
    else
      printf("Rule %d added successfully...\n", r.rule_id );
  }
}

/* ******************************** */

void drop_packet_rule(const struct pfring_pkthdr *h) {
  const struct pkt_parsing_info *hdr = &h->extended_hdr.parsed_pkt;
  static int rule_id=0;

  if(add_drop_rule == 1) {
    hash_filtering_rule rule;

    memset(&rule, 0, sizeof(hash_filtering_rule));

    rule.rule_id = rule_id++;
    rule.vlan_id = hdr->vlan_id;
    rule.proto = hdr->l3_proto;
    rule.ip_version = hdr->ip_version;
    rule.rule_action = dont_forward_packet_and_stop_rule_evaluation;
    rule.host4_peer_a = hdr->ip_src.v4, rule.host4_peer_b = hdr->ip_dst.v4;
    rule.port_peer_a = hdr->l4_src_port, rule.port_peer_b = hdr->l4_dst_port;

    if(pfring_handle_hash_filtering_rule(pd, &rule, 1 /* add_rule */) < 0)
      fprintf(stderr, "pfring_handle_hash_filtering_rule(1) failed\n");
    else if (!quiet)
      printf("Added filtering rule %d\n", rule.rule_id);
  } else {
    filtering_rule rule;
    int rc;

    memset(&rule, 0, sizeof(rule));

    rule.rule_id = rule_id++;
    rule.rule_action = dont_forward_packet_and_stop_rule_evaluation;
    rule.core_fields.proto = hdr->l3_proto;
    rule.core_fields.shost.v4 = hdr->ip_src.v4, rule.core_fields.shost_mask.v4 = 0xFFFFFFFF;
    rule.core_fields.sport_low = rule.core_fields.sport_high = hdr->l4_src_port;

    rule.core_fields.dhost.v4 = hdr->ip_dst.v4, rule.core_fields.dhost_mask.v4 = 0xFFFFFFFF;
    rule.core_fields.dport_low = rule.core_fields.dport_high = hdr->l4_dst_port;

    if((rc = pfring_add_filtering_rule(pd, &rule)) < 0)
      fprintf(stderr, "pfring_add_filtering_rule(2) failed\n");
    else if (!quiet)
      printf("Rule %d added successfully...\n", rule.rule_id);
  }
}

/* ******************************** */

void sigproc(int sig) {
  static int called = 0;

  if (!quiet)
    fprintf(stderr, "Leaving...\n");

  if(called) return; else called = 1;
  stats->do_shutdown = 1;

  if (!quiet)
    print_stats();

  pfring_breakloop(pd);
}

/* ******************************** */

void my_sigalarm(int sig) {
  if(stats->do_shutdown)
    return;

  print_stats();
  alarm(ALARM_SLEEP);
  signal(SIGALRM, my_sigalarm);
}

/* ****************************************************** */

static char *etheraddr_string(const u_char *ep, char *buf) {
  char *hex = "0123456789ABCDEF";
  u_int i, j;
  char *cp;

  cp = buf;
  if((j = *ep >> 4) != 0)
    *cp++ = hex[j];
  else
    *cp++ = '0';

  *cp++ = hex[*ep++ & 0xf];

  for(i = 5; (int)--i >= 0;) {
    *cp++ = ':';
    if((j = *ep >> 4) != 0)
      *cp++ = hex[j];
    else
      *cp++ = '0';

    *cp++ = hex[*ep++ & 0xf];
  }

  *cp = '\0';
  return (buf);
}

/* ****************************************************** */

static int32_t thiszone;

static char *intoa(unsigned int addr) {
  static char buf[sizeof "ff:ff:ff:ff:ff:ff:255.255.255.255"];
  return(_intoa(addr, buf, sizeof(buf)));
}

u_int32_t CalcDeltaTimeval(struct timeval ts_start, struct timeval ts_end) {
  // Caller should guarantee ts_end is later than ts_start.
  if (ts_start.tv_sec == ts_end.tv_sec) {
    return ts_end.tv_usec - ts_start.tv_usec;
  } else {
    return (ts_end.tv_sec - ts_start.tv_sec - 1) * 1000000 +
        (ts_end.tv_usec + 1000000 - ts_start.tv_usec);
  }
}

void process_packet(const struct pfring_pkthdr *h, const u_char *p, u_int8_t dump_match) {
  memset((void *) &h->extended_hdr.parsed_pkt, 0, sizeof(struct pkt_parsing_info));
  pfring_parse_pkt((u_char *) p, (struct pfring_pkthdr *) h, 5, 0, 1);

  // TODO: add support for UDP and IPv6.
  if (h->extended_hdr.parsed_pkt.eth_type != 0x0800 /* IPv4*/ ||
      h->extended_hdr.parsed_pkt.l3_proto != IPPROTO_TCP /* TCP*/) {
    printf("Non IPV4 TCP\n");
    return;
  }

  int hash_index = h->extended_hdr.pkt_hash % DEFAULT_HASH_SIZE;
  struct Ipv4TcpFlowEntry* entry = flow_hash_map[hash_index];
  struct Ipv4TcpFlowEntry* prev = NULL;
  while (entry != NULL) {
    if ((!h->extended_hdr.rx_direction &&
         entry->src_ip == h->extended_hdr.parsed_pkt.ip_src.v4 &&
         entry->dst_ip == h->extended_hdr.parsed_pkt.ip_dst.v4 &&
         entry->src_port == h->extended_hdr.parsed_pkt.l4_src_port &&
         entry->dst_port == h->extended_hdr.parsed_pkt.l4_dst_port) ||
        (h->extended_hdr.rx_direction &&
         entry->src_ip == h->extended_hdr.parsed_pkt.ip_dst.v4 &&
         entry->dst_ip == h->extended_hdr.parsed_pkt.ip_src.v4 &&
         entry->src_port == h->extended_hdr.parsed_pkt.l4_dst_port &&
         entry->dst_port == h->extended_hdr.parsed_pkt.l4_src_port)) {
      break;
    }

    prev = entry;
    entry = entry->next;
  }

  if (entry == NULL) {
    // Ignore flows started before dump, as well as packets after FIN.
    if (h->extended_hdr.rx_direction ||
        (h->extended_hdr.parsed_pkt.tcp.flags & FLAG_SYN) == 0) {
      return;
    }

    entry = (struct Ipv4TcpFlowEntry*)malloc(sizeof(struct Ipv4TcpFlowEntry));
    entry->src_ip = h->extended_hdr.parsed_pkt.ip_src.v4;
    entry->dst_ip = h->extended_hdr.parsed_pkt.ip_dst.v4;
    entry->src_port = h->extended_hdr.parsed_pkt.l4_src_port;
    entry->dst_port = h->extended_hdr.parsed_pkt.l4_dst_port;
    entry->out_bytes = 0;
    entry->out_packets = 0;
    entry->retrans_bytes = 0;
    entry->retrans_packets = 0;
    entry->max_rtt_usec = 0;
    entry->min_rtt_usec = 10000000;
    entry->ts_first = h->ts;
    entry->ts_last = h->ts;
    entry->max_seq_no = h->extended_hdr.parsed_pkt.tcp.seq_num;
    entry->prev = prev;
    entry->next = NULL;
    entry->seq_no_in_flight_head = NULL;
    entry->seq_no_in_flight_tail = NULL;
    
    if (prev != NULL) {
      prev->next = entry;
    } else {
      flow_hash_map[hash_index] = entry;
    }
  }

  if (!h->extended_hdr.rx_direction &&
      h->len > h->extended_hdr.parsed_pkt.offset.payload_offset) {
    // Only data packet is considered.
    u_int32_t payload_length =
        h->len - h->extended_hdr.parsed_pkt.offset.payload_offset;
    entry->out_bytes += payload_length;
    entry->out_packets += 1;
    entry->ts_last = h->ts;
    if (entry->max_seq_no > h->extended_hdr.parsed_pkt.tcp.seq_num) {
      entry->retrans_bytes += payload_length;
      entry->retrans_packets += 1;
      // TODO: Handle retransmission and sack.
    } else {
      entry->max_seq_no = h->extended_hdr.parsed_pkt.tcp.seq_num;

      struct SeqNoInFlight* seq_no_in_flight =
          (struct SeqNoInFlight*)malloc(sizeof(struct SeqNoInFlight));
      seq_no_in_flight->pending_ack_no =
          h->extended_hdr.parsed_pkt.tcp.seq_num + payload_length;
      seq_no_in_flight->ts_sent = h->ts;
      seq_no_in_flight->next = NULL;
      if (entry->seq_no_in_flight_head == NULL) {
        entry->seq_no_in_flight_head = seq_no_in_flight;
      } else {
        entry->seq_no_in_flight_tail->next = seq_no_in_flight;
      }
      entry->seq_no_in_flight_tail = seq_no_in_flight;
    }
  } else if (h->extended_hdr.rx_direction) {
    struct SeqNoInFlight* seq_no_in_flight = entry->seq_no_in_flight_head;
    while (seq_no_in_flight != NULL) {
      if (h->extended_hdr.parsed_pkt.tcp.ack_num <
          seq_no_in_flight->pending_ack_no) {
        entry->seq_no_in_flight_head = seq_no_in_flight;
        break;
      } else {
        if (h->extended_hdr.parsed_pkt.tcp.ack_num ==
            seq_no_in_flight->pending_ack_no) {
          u_int32_t new_rtt =
              CalcDeltaTimeval(seq_no_in_flight->ts_sent, h->ts);
          if (new_rtt > entry->max_rtt_usec) {
            entry->max_rtt_usec = new_rtt;
          }
          if (new_rtt < entry->min_rtt_usec) {
            entry->min_rtt_usec = new_rtt;
          }
        }
        struct SeqNoInFlight* seq_no_obsolete = seq_no_in_flight;
        seq_no_in_flight = seq_no_in_flight->next;
        free(seq_no_obsolete);
      }
    }
    if (seq_no_in_flight == NULL) {
      entry->seq_no_in_flight_head = NULL;
      entry->seq_no_in_flight_tail = NULL;
    }
  }

  if ((h->extended_hdr.parsed_pkt.tcp.flags & FLAG_FIN) != 0) {
    printf("%s:%d %s:%d [%lld.%06u -> %lld.%06u] %lu/%u (%lu/%u) (%u/%u) [FIN]\n",
        intoa(entry->src_ip), entry->src_port,
        intoa(entry->dst_ip), entry->dst_port,
        (long long)entry->ts_first.tv_sec, (u_int32_t)entry->ts_first.tv_usec,
        (long long)entry->ts_last.tv_sec, (u_int32_t)entry->ts_last.tv_usec,
        entry->out_bytes, entry->out_packets,
        entry->retrans_bytes, entry->retrans_packets,
        entry->max_rtt_usec, entry->min_rtt_usec);

    if (entry->prev != NULL) {
      entry->prev->next = entry->next;
    }
    if (entry->next != NULL) {
      entry->next->prev = entry->prev;
    }
    struct SeqNoInFlight* seq_no_left = entry->seq_no_in_flight_head;
    while (seq_no_left != NULL) {
      entry->seq_no_in_flight_head = seq_no_left->next;
      free(seq_no_left);
      seq_no_left = entry->seq_no_in_flight_head;
    }
    free(entry);
  }

  /*snprintf(dump_str, sizeof(dump_str), "%lld.%06u ", (long long)h->ts.tv_sec, h->ts.tv_usec);

  if(use_extended_pkt_header) {
    char bigbuf[4096];
    u_int len;

    snprintf(&dump_str[strlen(dump_str)], sizeof(dump_str)-strlen(dump_str),
        "%s", h->extended_hdr.rx_direction ? "[RX]" : "[TX]");

    pfring_print_parsed_pkt(bigbuf, sizeof(bigbuf), p, h);
    len = strlen(bigbuf);

    if(len > 0) bigbuf[len-1] = '\0';

    snprintf(&dump_str[strlen(dump_str)], sizeof(dump_str)-strlen(dump_str), "%s", bigbuf);
  } else {
    char buf1[32], buf2[32];
    struct ether_header *ehdr = (struct ether_header *) p;

    snprintf(&dump_str[strlen(dump_str)], sizeof(dump_str)-strlen(dump_str), 
             "[%s -> %s][eth_type=0x%04X][caplen=%d][len=%d]",
	     etheraddr_string(ehdr->ether_shost, buf1),
	     etheraddr_string(ehdr->ether_dhost, buf2),
	     ntohs(ehdr->ether_type),
	     h->caplen, h->len);     
  }

  if(verbose && h->len > min_len) printf("%s\n", dump_str);*/
}

/* ****************************************************** */

void dummyProcessPacket(const struct pfring_pkthdr *h,
			 const u_char *p, const u_char *user_bytes) {
  long threadId = (long)user_bytes;
  u_int8_t dump_match = !!dumper;

  stats->numPkts[threadId]++, stats->numBytes[threadId] += h->len+24 /* 8 Preamble + 4 CRC + 12 IFG */;

  if (unlikely(check_ts && h->ts.tv_sec != last_ts)) {
    if (h->ts.tv_sec < last_ts)
      printf("Bad timestamp [expected ts >= %ld][received ts = %ld]\n", 
        last_ts, h->ts.tv_sec);
    last_ts = h->ts.tv_sec;
  }

  if (unlikely(check_seq_ip)) {
    const struct pkt_parsing_info *hdr = &h->extended_hdr.parsed_pkt;
    if(!h->ts.tv_sec) pfring_parse_pkt((u_char *) p, (struct pfring_pkthdr *) h, 4, 0, 1);
    if (hdr->offset.l4_offset && hdr->ip_version == 4) {
      if (last_ip && last_ip+1 != hdr->ip_src.v4)
        printf("Bad IP [expected %u][received %u]\n", last_ip + 1, hdr->ip_src.v4);
      last_ip = hdr->ip_src.v4;
    }
  }

  if(touch_payload) {
    volatile int __attribute__ ((unused)) i;
    i = p[12] + p[13];
  }

  if(memcpy_test)
    memcpy((void *) memcpy_test_buffer, p, h->caplen);

  if(unlikely(add_drop_rule)) {
    if(!h->ts.tv_sec) pfring_parse_pkt((u_char*)p, (struct pfring_pkthdr*)h, 4, 0, 1);
    if (h->extended_hdr.parsed_pkt.offset.l4_offset) /* IP packet */
      drop_packet_rule(h);
  }

  if (dumper) {
    if(unlikely(do_close_dump)) openDump();
    if (dumper) {
      if (!h->ts.tv_sec) gettimeofday(&((struct pfring_pkthdr *) h)->ts, NULL);
      pcap_dump((u_char*)dumper, (struct pcap_pkthdr*)h, p);
      pcap_dump_flush(dumper);
    }
  }

  if(unlikely(verbose || dump_match)) {
    process_packet(h, p, dump_match);
  }

  if (unlikely(num_packets && num_packets == stats->numPkts[threadId]))
    sigproc(0);
}

/* *************************************** */

void printDevs() {
  pfring_if_t *dev;
  int i = 0;

  dev = pfring_findalldevs();

  if (verbose)
    printf("Name\tSystemName\tModule\tMAC\tBusID\tNumaNode\tStatus\tLicense\tExpiration\n");
  else
    printf("Available devices (-i):\n");

  while (dev != NULL) {
    if (verbose) {
      printf("%s\t%s\t%s\t", 
        dev->name, dev->system_name ? dev->system_name : "unknown", dev->module);

      if (dev->sn)
        printf("%s", dev->sn);
      else
        printf("%02X:%02X:%02X:%02X:%02X:%02X", 
          dev->mac[0] & 0xFF, dev->mac[1] & 0xFF, dev->mac[2] & 0xFF, 
          dev->mac[3] & 0xFF, dev->mac[4] & 0xFF, dev->mac[5] & 0xFF);

      printf("\t%04X:%02X:%02X.%X\t%d\t%s\t%s\t%ld\n",
        dev->bus_id.slot, dev->bus_id.bus, dev->bus_id.device, dev->bus_id.function,
        busid2node(dev->bus_id.slot, dev->bus_id.bus, dev->bus_id.device, dev->bus_id.function),
        dev->status ? "Up" : "Down", dev->license ? "Valid" : "NotFound", dev->license_expiration);
    } else {
      printf(" %d. %s\n", i++, dev->name);
    }
    dev = dev->next;
  }
}

/* *************************************** */

void printHelp(void) {
  printf("pfflowdump - (C) 2005-2019 ntop.org\n\n");
  printf("-h              Print this help\n");
  printf("-i <device>     Device name. Use:\n"
	 "                - ethX@Y for channels\n"
	 "                - zc:ethX for ZC devices\n"
	 );
  printf("-n <threads>      Number of polling threads (default %d)\n", num_threads);
  printf("-f <filter>       BPF filter\n");
  printf("-e <direction>    0=RX+TX, 1=RX only, 2=TX only\n");
  printf("-l <len>          Capture length\n");
  printf("-g <core_id>      Bind this app to a core\n");
  printf("-d <device>       Device on which incoming packets are copied\n");
  printf("-w <watermark>    Watermark\n");
  printf("-p <poll wait>    Poll wait (msec)\n");
  printf("-b <cpu %%>        CPU pergentage priority (0-99)\n");
  printf("-a                Active packet wait\n");
  printf("-N <num>          Read <num> packets and exit\n");
  printf("-m                Long packet header (with PF_RING extensions)\n");
  printf("-r                Rehash RSS packets\n");
  printf("-c <cluster id>   Cluster ID (kernel clustering)\n");
  printf("-H <cluster hash> Cluster hash type (kernel clustering)\n"
         "                   %d - src ip,           dst ip \n"
         "                   %d - src ip, src port, dst ip, dst port\n"
         "                   %d - src ip, src port, dst ip, dst port, proto (default)\n"
         "                   %d - src ip, src port, dst ip, dst port, proto, vlan\n"
         "                   %d - src ip, src port, dst ip, dst port, proto for TCP, src ip, dst ip otherwise\n"
         "                   %d - tunneled src ip,           dst ip\n"
         "                   %d - tunneled src ip, src port, dst ip, dst port\n"
         "                   %d - tunneled src ip, src port, dst ip, dst port, proto (default)\n"
         "                   %d - tunneled src ip, src port, dst ip, dst port, proto, vlan\n"
         "                   %d - tunneled src ip, src port, dst ip, dst port, proto for TCP, src ip, dst ip otherwise\n"
         "                   %d - round-robin\n"
	 "                   %d - src + dst ip (with duplication)\n",
    cluster_per_flow_2_tuple, cluster_per_flow_4_tuple,
    cluster_per_flow_5_tuple, cluster_per_flow,
    cluster_per_flow_tcp_5_tuple,
    cluster_per_inner_flow_2_tuple, cluster_per_inner_flow_4_tuple,
    cluster_per_inner_flow_5_tuple, cluster_per_inner_flow,
    cluster_per_inner_flow_tcp_5_tuple,
	 cluster_round_robin, cluster_per_flow_ip_with_dup_tuple);
  printf("-s              Enable hw timestamping\n");
  printf("-S              Do not strip hw timestamps (if present)\n");
  printf("-t              Touch payload (to force packet load on cache)\n");
  printf("-M              Packet memcpy (to test memcpy speed)\n");
  printf("-C <mode>       Work with the adapter in chunk mode (1=chunk API, 2=packet API)\n");
  printf("-T              Check packet timestamps\n");
  printf("-U              Check packet sequential IP as generated by pfsend -b <num IPs>\n");
  printf("-o <path>       Dump packets on the specified pcap\n");
  printf("-u <1|2>        For each incoming packet add a drop rule (1=hash, 2=wildcard rule)\n");
  printf("-J              Do not enable promiscuous mode\n");
  printf("-R              Do not reprogram RSS indirection table (Intel ZC only)\n");
  printf("-v <mode>       Verbose [1: verbose, 2: very verbose (print packet payload)]\n");
  printf("-K <len>        Print only packets with length > <len> with -v\n");
  printf("-L              List all interfaces and exit (use -v for more info)\n");
}

/* *************************************** */

void* packet_consumer_thread(void* _id) {
  long thread_id = (long)_id;
  u_int numCPU = sysconf( _SC_NPROCESSORS_ONLN );
  u_char buffer[NO_ZC_BUFFER_LEN];
  u_char *buffer_p = buffer;

  u_long core_id = thread_id % numCPU;
  struct pfring_pkthdr hdr;

  /* printf("packet_consumer_thread(%lu)\n", thread_id); */

  if((num_threads > 1) && (numCPU > 1)) {
    if(bind2core(core_id) == 0)
      if (!quiet)
        printf("Set thread %lu on core %lu/%u\n", thread_id, core_id, numCPU);
  }

  memset(&hdr, 0, sizeof(hdr));

  while(1) {
    int rc;
    u_int len;

    if(stats->do_shutdown) break;

    if((rc = pfring_recv(pd, &buffer_p, NO_ZC_BUFFER_LEN, &hdr, wait_for_packet)) > 0) {
      if(stats->do_shutdown) break;
      dummyProcessPacket(&hdr, buffer, (u_char*)thread_id);
#ifdef TEST_SEND
      buffer[0] = 0x99;
      buffer[1] = 0x98;
      buffer[2] = 0x97;
      pfring_send(pd, buffer, hdr.caplen);
#endif
    } else {
      if(wait_for_packet == 0) sched_yield();
    }

    if(0) {
      struct simple_stats {
	u_int64_t num_pkts, num_bytes;
      };
      struct simple_stats stats;

      len = sizeof(stats);
      rc = pfring_get_filtering_rule_stats(pd, 5, (char*)&stats, &len);
      if(rc < 0)
	fprintf(stderr, "pfring_get_filtering_rule_stats() failed [rc=%d]\n", rc);
      else {
        if (!quiet)
	  printf("[Pkts=%u][Bytes=%u]\n",
	         (unsigned int)stats.num_pkts,
	         (unsigned int)stats.num_bytes);
      }
    }
  }

  return(NULL);
}

/* *************************************** */

void* chunk_consumer_thread(void* _id) {
  long thread_id = (long)_id;
  u_int numCPU = sysconf( _SC_NPROCESSORS_ONLN );
  void *chunk_p = NULL;
  pfring_chunk_info chunk_info;

  u_long core_id = thread_id % numCPU;
  struct pfring_pkthdr hdr;

  /* printf("packet_consumer_thread(%lu)\n", thread_id); */

  if((num_threads > 1) && (numCPU > 1)) {
    if(bind2core(core_id) == 0)
      if (!quiet)
        printf("Set thread %lu on core %lu/%u\n", thread_id, core_id, numCPU);
  }

  memset(&hdr, 0, sizeof(hdr));

  while(1) {
    if(stats->do_shutdown) break;

    if(pfring_recv_chunk(pd, &chunk_p, &chunk_info, wait_for_packet) > 0) {
      if(stats->do_shutdown) break;
      stats->numPkts[thread_id]++, stats->numBytes[thread_id] += chunk_info.length;
    } else {
      if(wait_for_packet == 0) sched_yield();
    }
  }

  return(NULL);
}

/* *************************************** */

void openDump() {
  static u_int dump_id = 0;
  char path[256];

  dump_id++;

  if (strcmp(out_pcap_file, "-") != 0)
    snprintf(path, sizeof(path), "%s.%u", out_pcap_file, dump_id);
  else 
    snprintf(path, sizeof(path), "-");

  if(dumper != NULL) {
    pcap_dump_close(dumper);
    dumper = NULL;
  }

  if(match_dumper != NULL) {
    fclose(match_dumper);
    match_dumper = NULL;
  }

  dumper = pcap_dump_open(pcap_open_dead(DLT_EN10MB, 16384 /* MTU */), path);

  if(dumper == NULL)
    fprintf(stderr, "Unable to create dump file %s\n", path);

  do_close_dump = 0;
}

/* *************************************** */

void dumpMatch(char *str) {
  if(match_dumper != NULL) {
    fprintf(match_dumper, "%s", str);
    fflush(match_dumper);
  }
}

/* *************************************** */

void handleSigHup(int signalId) {
  do_close_dump = 1;
}

/* *************************************** */

#define MAX_NUM_STRINGS  32

int main(int argc, char* argv[]) {
  char *device = NULL, c, buf[32], path[256] = { 0 }, *reflector_device = NULL;
  u_char mac_address[6] = { 0 };
  int promisc = 1, snaplen = DEFAULT_SNAPLEN, rc;
  u_int clusterId = 0;
  u_int8_t list_interfaces = 0;
  u_int32_t flags = 0;
  int bind_core = -1;
  packet_direction direction = rx_and_tx_direction;
  u_int16_t watermark = 0, poll_duration = 0,
    cpu_percentage = 0, rehash_rss = 0;
  char *bpfFilter = NULL;
  cluster_type cluster_hash_type = cluster_per_flow_5_tuple;

  startTime.tv_sec = 0;
  thiszone = gmt_to_local(0);

  while((c = getopt(argc,argv,"hi:c:C:d:H:Jl:Lv:ae:n:w:o:p:qb:rg:u:mtsSx:f:z:N:MRTUK:")) != '?') {
    if((c == 255) || (c == -1)) break;

    switch(c) {
    case 'h':
      printHelp();
      exit(0);
      break;
    case 'a':
      wait_for_packet = 0;
      break;
    case 'b':
      cpu_percentage = atoi(optarg);
      break;
    case 'c':
      clusterId = atoi(optarg);
      break;
    case 'C':
      chunk_mode = atoi(optarg);
      break;
    case 'd':
      reflector_device = strdup(optarg);
      break;
    case 'e':
      switch(atoi(optarg)) {
      case rx_and_tx_direction:
      case rx_only_direction:
      case tx_only_direction:
	direction = atoi(optarg);
	break;
      }
      break;
    case 'f':
      bpfFilter = strdup(optarg);
      break;
    case 'g':
      bind_core = atoi(optarg);
      break;
    case 'H':
      {
	int id = atoi(optarg);

	if(id <= MAX_CLUSTER_TYPE_ID) 
          cluster_hash_type = id;
	else
	  fprintf(stderr, "WARNING: Invalid hash type %u\n", atoi(optarg));
      }
      break;
    case 'i':
      device = strdup(optarg);
      break;
    case 'J':
      promisc = 0;
      break;
    case 'l':
      snaplen = atoi(optarg);
      break;
    case 'L':
      list_interfaces = 1;
      break;
    case 'm':
      use_extended_pkt_header = 1;
      break;
    case 'M':
      memcpy_test = 1;
      break;
    case 'n':
      num_threads = atoi(optarg);
      break;
    case 'N':
      num_packets = atoi(optarg);
      break;
    case 'o':
      out_pcap_file = optarg;
      if (strcmp(out_pcap_file, "-") == 0) quiet = 1; 
      break;
    case 'p':
      poll_duration = atoi(optarg);
      break;
    case 'r':
      rehash_rss = 1;
      break;
    case 's':
      enable_hw_timestamp = 1;
      break;
    case 'S':
      dont_strip_timestamps = 1;
      break;
    case 'T':
      check_ts = 1;
      last_ts = time(NULL);
      break;
    case 't':
      touch_payload = 1;
      break;
    case 'u':
      switch(add_drop_rule = atoi(optarg)) {
      case 1:
	fprintf(stderr, "Adding hash filtering rules\n");
	break;
      default:
	fprintf(stderr, "Adding wildcard filtering rules\n");
	add_drop_rule = 2;
	break;
      }
      use_extended_pkt_header = 1;
      break;
    case 'U':
      check_seq_ip = 1;
      use_extended_pkt_header = 1;
      break;
    case 'v':
      if(optarg[0] == '1')
	verbose = 1;
      else if(optarg[0] == '2')
	verbose = 2;
      else {
	printHelp();
        exit(-1);
      }
      use_extended_pkt_header = 1;
      break;
    case 'w':
      watermark = atoi(optarg);
      break;
    case 'K':
      min_len = atoi(optarg);
      break;
    case 'R':
      asymm_rss = 1;
      break;
    }
  }

  if (list_interfaces) {
    printDevs();
    exit(0);
  }

  if(verbose) watermark = 1;
  if(device == NULL) device = DEFAULT_DEVICE;
  if(num_threads > MAX_NUM_THREADS) num_threads = MAX_NUM_THREADS;
  if(chunk_mode) num_threads = 1;

  bind2node(bind_core);

  if ((stats = calloc(1, sizeof(struct app_stats))) == NULL)
    return -1;

  if(wait_for_packet && (cpu_percentage > 0)) {
    if(cpu_percentage > 99) cpu_percentage = 99;
    pfring_config(cpu_percentage);
  }

  if(out_pcap_file) {
    openDump();

    if(dumper == NULL) return(-1);

    (void)signal(SIGHUP, handleSigHup);

    if(num_threads > 1) {
      fprintf(stderr, "WARNING: Disabling threads when using -o\n");
      num_threads = 1;
    }
  }

  if(num_threads > 1)         flags |= PF_RING_REENTRANT;
  if(use_extended_pkt_header) flags |= PF_RING_LONG_HEADER;
  if(promisc)                 flags |= PF_RING_PROMISC;
  if(enable_hw_timestamp)     flags |= PF_RING_HW_TIMESTAMP;
  if(!dont_strip_timestamps)  flags |= PF_RING_STRIP_HW_TIMESTAMP;
  if(chunk_mode)              flags |= PF_RING_CHUNK_MODE;
  if(asymm_rss)               flags |= PF_RING_ZC_NOT_REPROGRAM_RSS;
  else                        flags |= PF_RING_ZC_SYMMETRIC_RSS;  /* Note that symmetric RSS is ignored by non-ZC drivers */
  /* flags |= PF_RING_FLOW_OFFLOAD | PF_RING_FLOW_OFFLOAD_NOUPDATES;  to receive FlowID on supported adapters*/
  /* flags |= PF_RING_USERSPACE_BPF; to force userspace BPF even with kernel capture  */

  pd = pfring_open(device, snaplen, flags);

  if(pd == NULL) {
    fprintf(stderr, "pfring_open error [%s] (pf_ring not loaded or interface %s is down ?)\n",
	    strerror(errno), device);
    return(-1);
  } else {
    u_int32_t version;

    pfring_set_application_name(pd, "pfflowdump");
    pfring_version(pd, &version);

    if (!quiet)
      printf("Using PF_RING v.%d.%d.%d\n",
             (version & 0xFFFF0000) >> 16,
             (version & 0x0000FF00) >> 8,
             version & 0x000000FF);
  }

  int ifindex = -1;
  rc = pfring_get_bound_device_address(pd, mac_address);
  pfring_get_bound_device_ifindex(pd, &ifindex);
  if (!quiet)
    printf("Capturing from %s [mac: %s][if_index: %d][speed: %uMb/s]\n",
           device, rc == 0 ? etheraddr_string(mac_address, buf) : "unknown",
           ifindex, pfring_get_interface_speed(pd));

  if (!quiet) {
    printf("# Device RX channels: %d\n", pfring_get_num_rx_channels(pd));
    printf("# Polling threads:    %d\n", num_threads);
  }

  if (enable_hw_timestamp) {
    struct timespec ltime;
    /* Setting current clock (please note that with standard driver this is not mandatory) */
    if ((clock_gettime(CLOCK_REALTIME, &ltime) != 0 ||
        pfring_set_device_clock(pd, &ltime) < 0) && pd->zc_device)
      fprintf(stderr, "Error setting device clock\n");
  }

  if((rc = pfring_set_direction(pd, direction)) != 0)
    ; //fprintf(stderr, "pfring_set_direction returned %d (perhaps you use a direction other than rx only with ZC?)\n", rc);

  if((rc = pfring_set_socket_mode(pd, recv_only_mode)) != 0)
    fprintf(stderr, "pfring_set_socket_mode returned [rc=%d]\n", rc);

  if(bpfFilter != NULL) {
    rc = pfring_set_bpf_filter(pd, bpfFilter);
    if(rc != 0)
      fprintf(stderr, "pfring_set_bpf_filter(%s) returned %d\n", bpfFilter, rc);
    else if (!quiet)
      printf("Successfully set BPF filter '%s'\n", bpfFilter);
  }

  if(clusterId > 0) {
    rc = pfring_set_cluster(pd, clusterId, cluster_hash_type);
    fprintf(stderr, "pfring_set_cluster returned %d\n", rc);
  }

  if(watermark > 0) {
    if((rc = pfring_set_poll_watermark(pd, watermark)) != 0)
      fprintf(stderr, "pfring_set_poll_watermark returned [rc=%d][watermark=%d]\n", rc, watermark);
  }

  if(reflector_device != NULL) {
    rc = pfring_set_reflector_device(pd, reflector_device);

    if(rc == 0) {
      /*if (!quiet)
       * printf("pfring_set_reflector_device(%s) succeeded\n", reflector_device); */
    } else
      fprintf(stderr, "pfring_set_reflector_device(%s) failed [rc: %d]\n", reflector_device, rc);
  }

  if(rehash_rss)
    pfring_enable_rss_rehash(pd);

  if(poll_duration > 0)
    pfring_set_poll_duration(pd, poll_duration);

  signal(SIGINT, sigproc);
  signal(SIGTERM, sigproc);

  if(!verbose && ! quiet) {
    signal(SIGALRM, my_sigalarm);
    alarm(ALARM_SLEEP);
  }

  pfring_set_application_stats(pd, "Statistics not yet computed: please try again...");
  if(pfring_get_appl_stats_file_name(pd, path, sizeof(path)) != NULL)
    fprintf(stderr, "Dumping statistics on %s\n", path);

  if (pfring_enable_ring(pd) != 0) {
    fprintf(stderr, "Unable to enable ring :-(\n");
    pfring_close(pd);
    return(-1);
  }

  sample_filtering_rules();

  if(num_threads <= 1) {
    if(bind_core >= 0)
      bind2core(bind_core);

    if (chunk_mode == 1) {
      chunk_consumer_thread(0);
    } else {
      pfring_loop(pd, dummyProcessPacket, (u_char*)NULL, wait_for_packet);
    }
  } else {
    pthread_t my_thread;
    long i;

    for(i=0; i<num_threads; i++)
      pthread_create(&my_thread, NULL, packet_consumer_thread, (void*)i);

    for(i=0; i<num_threads; i++)
      pthread_join(my_thread, NULL);
  }

  sleep(1);
  pfring_close(pd);
  if(dumper) pcap_dump_close(dumper);
  return(0);
}