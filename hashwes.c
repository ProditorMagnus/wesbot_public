/* wesirc 0.4 (June 2010)
 * Copyright (C) 2010 Norbert de Jonge <nlmdejonge@telfort.nl>
 *
 * This program is free software: you can redistribute it and/or modify it
 * under the terms of the GNU General Public License as published by the Free
 * Software Foundation, either version 3 of the License, or (at your option)
 * any later version.
 *
 * This program is distributed in the hope that it will be useful, but WITHOUT
 * ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
 * FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for
 * more details.
 *
 * You should have received a copy of the GNU General Public License along with
 * this program. If not, see [ www.gnu.org/licenses/ ].
 */

/* Added more WSRSW features; see function ProcessWhisper.
 *
 * Remember to change the defines under "CHANGE THESE VALUES" first.
 */

/*************************************/
//#include <sys/socket.h>
//#include <netinet/in.h>
//#include <netdb.h>
#include <string.h>
#include <stdio.h>
#include <unistd.h>
#include <errno.h>
#include <fcntl.h>
// #include <zlib.h>
#include <stdlib.h>
#include <openssl/md5.h>
//#include <mysql.h>
#include <time.h>
#include <locale.h>
// #include <langinfo.h>
#include <ctype.h>
/*************************************/
/*        CHANGE THESE VALUES        */
/*************************************/
#define SERV_HOST_ADDR "server.wesnoth.org"
#define SERV_HOST_PORT 15000
#define NICK "nick"
#define PASSWORD "password"
#define BOT_VERSION "version"
#define BOT_MASTER "master_nick"
/*************************************/
#define MAX_STRING 250
#define RECEIVED "received.gz"
#define SENDING "sending"
#define BUFLEN 50000
#define EXIT_ERROR 1
#define VERSION "[version]\n\tversion=\"1.8.2\"\n[/version]"
#define LOGIN "[login]\n\tselective_ping=\"1\"\n\tusername=\"" NICK "\"\n[/login]"
#define MAX_VARS 100
#define ENT_QUOTES 1
#define MAX_COMMENT 50
#define REGISTER "You'll need to register your nick at wsrsw.org first!"
#define VOTE_FORMAT "Wrong vote format!"
#define BOT_DESCRIPTION "Retrieves and stores data from and into the database back end of WSRSW (wsrsw.org)."
#define BOT_COMMANDS "List of available commands: http://www.wsrsw.org/commands.php"
/*************************************/
char sReceived[MAX_STRING];
char sToSend[MAX_STRING];
int iToSend;
char sVars[MAX_VARS][2][MAX_STRING];
int iVars;
const char *itoa64 = "./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";
char sEncoded[MAX_STRING];
/*************************************/
// void ProcessWhisper (int iSockFd);
// void ConnectToServer (char *sHostAddr, int *iSockFd, int iPort);
// void HandShake (int iSockFd);
// void WriteToSocket (int iSockFd, char *sString, int iChars, int iHandshake);
// int ReadFromSocket (int iSockFd, int iHandshake);
int SignedBytesToInt ();
void SaveReceived (int iReceived);
// int ParseServerData (char *uncompr, int iSockFd);
void SendReply (int iSockFd, char *sString);
void SaveToSend (char *sString);
void GzipAndLoadToSend ();
void EncodeHash (char *sDest, char *sSource, int iCount);
void CreateHash (char *sPassword, char *sSalt, int iIterationCount);
void GetMD5 (char *sInput, unsigned char *sResult, int iInputLength);
int GetIteration (char *sHash);
char *substr (const char *pstr, int start, int numchars);
int strpos (char *haystack, char *needle);
int IsRegistered (char *sNick);
void GiveHelp (char *sNick, int iSockFd);
void AddComment (char *sNick, char *sScenCom, int iSockFd);
void GetVotes (char *sNick, char *sScenWhose, int iSockFd);
void AddVotes (char *sNick, char *sScenVotes, int iSockFd);
void GiveMapp (char *sNick, char *sScen, int iSockFd);
void Whisper (int iSockFd, char *sFrom, char *sTo, char *sString);
char *htmlspecialchars (char *sString, int iTransQuotes);
char *str_replace (const char *sString, const char *sFrom, const char *sTo);

/*****************************************************************************/
int main (int argc, char *argv[])
/*****************************************************************************/
{
	// printf ("[  OK  ] Password. %s \n",argv[1]);
	// printf ("[  OK  ] Salt we received: %s (%i)\n", argv[2],strlen (argv[2]));
	if(argc<3){
		printf("too few arguments, %i",argc);
		return 1;
	}
	// CreateHash (htmlspecialchars (argv[1], ENT_QUOTES), substr (argv[2], 4, 8), GetIteration (argv[2]));
	CreateHash (argv[1], substr (argv[2], 4, 8), GetIteration (argv[2]));
	CreateHash (sEncoded, substr (argv[2], 12, 8), 10); /* 1024 */
	if (strlen (sEncoded) != 22)
	{
		printf ("[FAILED] Could not create a proper hash!\n");
		return 1;
		// exit (EXIT_ERROR);
	}
	// printf ("[  OK  ] Hash we created: %s (%i)\n", sEncoded,strlen (sEncoded));
	printf ("%s", sEncoded);
	// printf ("[login]\n\tpassword=\"%s\"\n\tpassword_reminder=\"\"\n\tselective_ping=\"1\"\n\tusername=\"%s\"\n[/login]", sEncoded, NICK);

	return 0;
}

/*****************************************************************************/
int SignedBytesToInt ()
/*****************************************************************************/
{
	int iNumber;
	int iLoop;

	iNumber = (unsigned char)sReceived[3];
	for (iLoop = 1; iLoop < 4; iLoop++)
	{
		iNumber = iNumber + ((iLoop * 256) * (unsigned char)sReceived[3 - iLoop]);
	}

	return (iNumber);
}

/*****************************************************************************/
void SaveReceived (int iReceived)
/*****************************************************************************/
{
	FILE *fp;

	fp = fopen(RECEIVED, "w");
	fwrite (sReceived, sizeof(char), iReceived, fp);
	fclose (fp);
}

/*****************************************************************************/
int ParseServerData (char *uncompr, int iSockFd)
/*****************************************************************************/
{
	int i;
	int iRight;
	char sLeft[MAX_STRING];
	char sRight[MAX_STRING];
	char sTemp[MAX_STRING];

	snprintf (sLeft, MAX_STRING, "%s", "");
	snprintf (sRight, MAX_STRING, "%s", "");
	iRight = 0;
	iVars = 0;
	for (i = 0; i <strlen(uncompr); i++)
	{
		switch (uncompr[i])
		{
			case '\n':
				iVars++;
				snprintf (sVars[iVars - 1][0], MAX_STRING, "%s", sLeft);
				snprintf (sVars[iVars - 1][1], MAX_STRING, "%s", sRight);
				if (strcmp (sLeft, "[/version]") == 0) { return (1); }
				if (strcmp (sLeft, "[/redirect]") == 0) { return (2); }
				if (strcmp (sLeft, "[/mustlogin]") == 0) { return (3); }
				if (strcmp (sLeft, "[/error]") == 0)
				{
					if (strcmp (sVars[1][1], "200") == 0) { return (5); }
					if (strcmp (sVars[1][1], "203") == 0) { exit (EXIT_ERROR); }
				}
				if (strcmp (sLeft, "[/whisper]") == 0)
				{
					if (strpos (sVars[2][1], NICK) == 0) { return (6); }
				}
				snprintf (sLeft, MAX_STRING, "%s", "");
				snprintf (sRight, MAX_STRING, "%s", "");
				iRight = 0;
				break;
			case '=':
				iRight = 1; break;
			default:
				switch (iRight)
				{
					case 0:
						snprintf (sTemp, MAX_STRING, "%s", sLeft);
						snprintf (sLeft, MAX_STRING, "%s%c", sTemp, uncompr[i]);
						break;
					case 1:
						if (uncompr[i] != '"')
						{
							snprintf (sTemp, MAX_STRING, "%s", sRight);
							snprintf (sRight, MAX_STRING, "%s%c", sTemp, uncompr[i]);
						}
						break;
				}
				break;
		}
	}
	if (strcmp (sRight, "") != 0)
	{
		iVars++;
		snprintf (sVars[iVars - 1][0], MAX_STRING, "%s", sLeft);
		snprintf (sVars[iVars - 1][1], MAX_STRING, "%s", sRight);
		return (4);
	}
	return (0);
}

/*****************************************************************************/
void SendReply (int iSockFd, char *sString)
/*****************************************************************************/
{
	SaveToSend (sString);
	GzipAndLoadToSend ();
	// WriteToSocket (iSockFd, sToSend, iToSend, 0);
}

/*****************************************************************************/
void SaveToSend (char *sString)
/*****************************************************************************/
{
	int iFd;

	if ((iFd = open (SENDING, O_WRONLY | O_CREAT, 0666)) == -1)
	{
		printf ("[FAILED] Could not open file!\n");
		exit (EXIT_ERROR);
	}
	if ((write (iFd, sString, strlen (sString))) != strlen (sString))
	{
		printf ("[FAILED] Could not save data!\n");
		exit (EXIT_ERROR);
	}
	close (iFd);
}

/*****************************************************************************/
void GzipAndLoadToSend ()
/*****************************************************************************/
{
	char sSystem[MAX_STRING];
	FILE *fp;
	char line[1 + 1];

	snprintf (sSystem, MAX_STRING, "gzip -n -f %s", SENDING);
	system (sSystem);
	if ((fp = fopen("sending.gz", "rb")) == NULL)
	{
		printf ("[FAILED] Could not open file!\n");
		exit (EXIT_ERROR);
	}
	iToSend = 0;
	while (fgets(line, sizeof(line), fp) != NULL)
	{
		sToSend[iToSend] = line[0];
		iToSend++;
	}
	fclose (fp);
}

/*****************************************************************************/
void EncodeHash (char *sDest, char *sSource, int iCount)
/*****************************************************************************/
{
	int i;
	int value;

	i = 0;
	do {
		value = (unsigned char)sSource[i++];
		*sDest++ = itoa64[value & 0x3f];
		if (i < iCount)
			value |= (unsigned char)sSource[i] << 8;
		*sDest++ = itoa64[(value >> 6) & 0x3f];
		if (i++ >= iCount)
			break;
		if (i < iCount)
			value |= (unsigned char)sSource[i] << 16;
		*sDest++ = itoa64[(value >> 12) & 0x3f];
		if (i++ >= iCount)
		break;
		*sDest++ = itoa64[(value >> 18) & 0x3f];
	} while (i < iCount);
}

/*****************************************************************************/
void CreateHash (char *sPassword, char *sSalt, int iIterationCount)
/*****************************************************************************/
{
	char sOutput[MAX_STRING];
	char sTemp[MAX_STRING];
	unsigned char sChecksum[16*2+1] = "";
	int iLoop;

	iIterationCount = 1 << iIterationCount;

	snprintf (sOutput, MAX_STRING, "%s", "");
	for (iLoop = 0; iLoop < strlen (sSalt); iLoop++)
	{
		snprintf (sTemp, MAX_STRING, "%s", sOutput);
		snprintf (sOutput, MAX_STRING, "%s%c", sTemp, (unsigned char)sSalt[iLoop]);
	}
	for (iLoop = 0; iLoop < strlen (sPassword); iLoop++)
	{
		snprintf (sTemp, MAX_STRING, "%s", sOutput);
		snprintf (sOutput, MAX_STRING, "%s%c", sTemp,
			(unsigned char)sPassword[iLoop]);
	}
	GetMD5 (sOutput, sChecksum, strlen (sSalt) + strlen (sPassword));
	snprintf (sOutput, MAX_STRING, "%s", sChecksum);

	do {
		for (iLoop = 0; iLoop < strlen(sPassword); iLoop++)
		{
			sOutput[iLoop + 16] = sPassword[iLoop];
		}
		sOutput[iLoop + 16] = '\0';
		GetMD5 (sOutput, sChecksum, 16 + strlen (sPassword));
		for (iLoop = 0; iLoop < 16; iLoop++) { sOutput[iLoop] = sChecksum[iLoop]; }
		sOutput[16] = '\0';
	} while (--iIterationCount);

	EncodeHash (sEncoded, sOutput, MD5_DIGEST_LENGTH);
}

/*****************************************************************************/
void GetMD5 (char *sInput, unsigned char *sResult, int iInputLength)
/*****************************************************************************/
{
	MD5_CTX ctx;

	MD5_Init(&ctx);
	MD5_Update(&ctx, sInput, iInputLength);
	MD5_Final(sResult, &ctx); /* places ctx in sResult */
}

/*****************************************************************************/
int GetIteration (char *sHash)
/*****************************************************************************/
{
	return (strlen (itoa64) - strlen (strchr (itoa64, sHash[3])));
}

/*****************************************************************************/
char *substr (const char *pstr, int start, int numchars)
/*****************************************************************************/
{
	char *pnew = malloc(numchars+1);
	strncpy(pnew, pstr + start, numchars);
	pnew[numchars] = '\0';
	return pnew;
}

/*****************************************************************************/
int strpos (char *haystack, char *needle)
/*****************************************************************************/
{
	char *p = strstr (haystack, needle);
	if (p) return p - haystack;
	return (-1);
}

/*****************************************************************************/
int IsRegistered (char *sNick)
/*****************************************************************************/
{
	return 0;
}

/*****************************************************************************/
void GiveHelp (char *sNick, int iSockFd)
/*****************************************************************************/
{
	char sSend[MAX_STRING];

	snprintf (sSend, MAX_STRING, "%s : %s : %s", NICK, BOT_VERSION, BOT_MASTER);
	Whisper (iSockFd, NICK, sNick, sSend);
	Whisper (iSockFd, NICK, sNick, BOT_DESCRIPTION);
	Whisper (iSockFd, NICK, sNick, BOT_COMMANDS);
}

/*****************************************************************************/
void Whisper (int iSockFd, char *sFrom, char *sTo, char *sString)
/*****************************************************************************/
{
	char sSend[MAX_STRING];

	snprintf (sSend, MAX_STRING, "[whisper]\n\tmessage=\"%s\"\n\treceiver=\"%s\"\n\tsender=\"%s\"\n[/whisper]", sString, sTo, sFrom);
	SendReply (iSockFd, sSend);
}

/*****************************************************************************/
char *htmlspecialchars (char *sString, int iTransQuotes)
/*****************************************************************************/
{
	char *sTemp = (char *) malloc (MAX_STRING * sizeof (char));

	snprintf (sTemp, MAX_STRING, "%s", sString);
	sTemp = str_replace (sTemp, "&", "&amp;");
	sTemp = str_replace (sTemp, "<", "&lt;");
	sTemp = str_replace (sTemp, ">", "&gt;");
	if (iTransQuotes == 1)
	{
		sTemp = str_replace (sTemp, "\"", "&quot;");
		sTemp = str_replace (sTemp, "'", "&#039;");
	}

	return (sTemp);
}

/*****************************************************************************/
char *str_replace (const char *sString, const char *sFrom, const char *sTo)
/*****************************************************************************/
{
  char *tok = NULL;
  char *newstr = NULL;

  tok = strstr (sString, sFrom);
  if (tok == NULL)
		return strdup (sString);
  newstr = malloc (strlen (sString) - strlen (sFrom) + strlen (sTo) + 1);
  if (newstr == NULL)
		return NULL;
  memcpy (newstr, sString, tok - sString);
  memcpy (newstr + (tok - sString), sTo, strlen (sTo));
  memcpy (newstr + (tok - sString) + strlen (sTo), tok + strlen (sFrom),
		strlen (sString) - strlen (sFrom) - (tok - sString));
  memset (newstr + strlen (sString) - strlen (sFrom) + strlen (sTo), 0, 1);

  return newstr;
}
