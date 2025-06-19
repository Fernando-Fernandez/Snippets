<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform" 
	xmlns:xs="http://www.w3.org/2001/XMLSchema" 
	exclude-result-prefixes="xs" version="1.0">

<xsl:output method="text"/>

<xsl:template match="/Workflow">

FullName	Active	triggerType	booleanFilter	criteriaItems	actions	timeTriggers	timeTriggeredActions
<xsl:for-each select="rules[active='true']">
	<xsl:apply-templates select="fullName" /> 
	<xsl:apply-templates select="active" /> 
	<xsl:apply-templates select="triggerType" /> 
	<xsl:apply-templates select="booleanFilter" /> 
	<xsl:value-of select="formula" />
	<xsl:for-each select="criteriaItems" > 
		<xsl:if test="position()>1">
			<xsl:text> | </xsl:text>
		</xsl:if> 
		<xsl:value-of select="concat( field, ' ', operation, ' ', value )" /> 
	</xsl:for-each> 
	<xsl:text>&#x9;</xsl:text> 
	<xsl:if test="not(actions)" >
		<xsl:text>&#x9;</xsl:text>
	</xsl:if> 
	<xsl:for-each select="actions" > 
		<xsl:if test="position()>1">
			<xsl:text> | </xsl:text>
		</xsl:if> 
		<xsl:value-of select="concat( name, ' (', type, ')' )" /> 
	</xsl:for-each>
	<xsl:text>&#x9;</xsl:text> 
	<xsl:for-each select="workflowTimeTriggers" > 
		<xsl:value-of select="concat( offsetFromField, ' ', timeLength, ' ', workflowTimeTriggerUnit, ' ' )" /> 
		<xsl:text>&#x9;</xsl:text> 
		<xsl:for-each select="actions" > 
			<xsl:if test="position()>1">
				<xsl:text> | </xsl:text>
			</xsl:if> 
			<xsl:value-of select="concat( name, ' (', type, ')' )" /> 
		</xsl:for-each> 
	</xsl:for-each> 
	<xsl:text>&#xA;</xsl:text>
</xsl:for-each>

==========================

FullName	Template	SenderType	SenderAddress	Recipients	CCTo
<xsl:for-each select="alerts">
    <xsl:apply-templates select="fullName" /> 
	<xsl:apply-templates select="template" /> 
	<xsl:apply-templates select="senderType" /> 
	<xsl:apply-templates select="senderAddress" /> 
	<xsl:for-each select="recipients" > 
		<xsl:if test="position()>1">
			<xsl:text>, </xsl:text>
		</xsl:if> 
		<xsl:if test="not(recipient) and not(field)">
			<xsl:value-of select="type" />
		</xsl:if> 
		<xsl:value-of select="recipient" /> 
		<xsl:value-of select="field" /> 
	</xsl:for-each> 
	<xsl:text>&#x9;</xsl:text> 
	<xsl:value-of select="ccEmails" /> 
	<xsl:text>&#xA;</xsl:text>
</xsl:for-each>
==========================

FullName	Field	SetToValue	notifyAssignee	reevaluateOnChange
<xsl:for-each select="fieldUpdates">
    <xsl:apply-templates select="fullName" /> 
	<xsl:apply-templates select="field" /> 
	<xsl:value-of select="literalValue|formula|lookupValue" /> 
	<xsl:if test="lookupValueType">
		<xsl:value-of select="concat( ' (', lookupValueType, ')' )" />
	</xsl:if> 
	<xsl:text>&#x9;</xsl:text> 
	<xsl:apply-templates select="notifyAssignee" /> 
	<xsl:apply-templates select="reevaluateOnChange" /> 
	<xsl:text>&#xA;</xsl:text>
</xsl:for-each>
==========================
</xsl:template>

<xsl:template match="fullName|active|template|field|triggerType|senderType|booleanFilter|senderAddress|notifyAssignee|reevaluateOnChange">
	<xsl:apply-templates /> <xsl:text>&#x9;</xsl:text>
</xsl:template>	

</xsl:stylesheet>
