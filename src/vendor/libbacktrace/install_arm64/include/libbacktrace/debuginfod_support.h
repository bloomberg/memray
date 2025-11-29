/* External declarations for the libdebuginfod client library.
   Copyright (C) 2019-2020 Red Hat, Inc.
   This file is part of elfutils.

   This file is free software; you can redistribute it and/or modify
   it under the terms of either

   * the GNU Lesser General Public License as published by the Free
       Software Foundation; either version 3 of the License, or (at
       your option) any later version

   or

   * the GNU General Public License as published by the Free
       Software Foundation; either version 2 of the License, or (at
       your option) any later version

   or both in parallel, as here.

   elfutils is distributed in the hope that it will be useful, but
   WITHOUT ANY WARRANTY; without even the implied warranty of
   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
   General Public License for more details.

   You should have received copies of the GNU General Public License and
   the GNU Lesser General Public License along with this program.  If
   not, see <http://www.gnu.org/licenses/>.  */

#ifndef _DEBUGINFOD_CLIENT_H
#define _DEBUGINFOD_CLIENT_H 1

/* Names of environment variables that control the client logic. */
#define DEBUGINFOD_URLS_ENV_VAR "DEBUGINFOD_URLS"
#define DEBUGINFOD_CACHE_PATH_ENV_VAR "DEBUGINFOD_CACHE_PATH"
#define DEBUGINFOD_TIMEOUT_ENV_VAR "DEBUGINFOD_TIMEOUT"
#define DEBUGINFOD_PROGRESS_ENV_VAR "DEBUGINFOD_PROGRESS"
#define DEBUGINFOD_VERBOSE_ENV_VAR "DEBUGINFOD_VERBOSE"
#define DEBUGINFOD_RETRY_LIMIT_ENV_VAR "DEBUGINFOD_RETRY_LIMIT"
#define DEBUGINFOD_MAXSIZE_ENV_VAR "DEBUGINFOD_MAXSIZE"
#define DEBUGINFOD_MAXTIME_ENV_VAR "DEBUGINFOD_MAXTIME"
#define DEBUGINFOD_HEADERS_FILE_ENV_VAR "DEBUGINFOD_HEADERS_FILE"

/* Handle for debuginfod-client connection.  */
typedef struct debuginfod_client debuginfod_client;

#ifdef __cplusplus
extern "C" {
#endif

/* Create a handle for a new debuginfod-client session.  */
debuginfod_client *debuginfod_begin (void);

/* Query the urls contained in $DEBUGINFOD_URLS for a file with
   the specified type and build id.  If build_id_len == 0, the
   build_id is supplied as a lowercase hexadecimal string; otherwise
   it is a binary blob of given length.

   If successful, return a file descriptor to the target, otherwise
   return a posix error code.  If successful, set *path to a
   strdup'd copy of the name of the same file in the cache.
   Caller must free() it later. */

int debuginfod_find_debuginfo (debuginfod_client *client,
			       const unsigned char *build_id,
                               int build_id_len,
                               char **path);

int debuginfod_find_executable (debuginfod_client *client,
				const unsigned char *build_id,
                                int build_id_len,
                                char **path);

int debuginfod_find_source (debuginfod_client *client,
			    const unsigned char *build_id,
                            int build_id_len,
                            const char *filename,
                            char **path);

int debuginfod_find_section (debuginfod_client *client,
			     const unsigned char *build_id,
			     int build_id_len,
			     const char *section,
			     char **path);

typedef int (*debuginfod_progressfn_t)(debuginfod_client *c, long a, long b);
void debuginfod_set_progressfn(debuginfod_client *c,
			       debuginfod_progressfn_t fn);

void debuginfod_set_verbose_fd(debuginfod_client *c, int fd);

/* Set the user parameter.  */
void debuginfod_set_user_data (debuginfod_client *client, void *value);

/* Get the user parameter.  */
void* debuginfod_get_user_data (debuginfod_client *client);

/* Get the current or last active URL, if known.  */
const char* debuginfod_get_url (debuginfod_client *client);

/* Returns set of x-debuginfod* header lines received from current or
   last active transfer, \n separated, if known. */
const char* debuginfod_get_headers(debuginfod_client *client);

/* Add an outgoing HTTP request  "Header: Value".  Copies string.  */
int debuginfod_add_http_header (debuginfod_client *client, const char* header);

/* Release debuginfod client connection context handle.  */
void debuginfod_end (debuginfod_client *client);

#ifdef __cplusplus
}
#endif


#endif /* _DEBUGINFOD_CLIENT_H */
